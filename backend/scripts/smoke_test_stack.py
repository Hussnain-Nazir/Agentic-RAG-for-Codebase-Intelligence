"""Build and exercise Prism's three-service Docker Compose stack."""

import argparse
import io
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "backend" / "tests" / "fixtures" / "mini_fastapi"
SERVICES = {"postgres", "backend", "frontend"}


class SmokeFailure(RuntimeError):
    pass


def compose_command(production: bool) -> list[str]:
    command = ["docker", "compose"]
    if production:
        command.extend(["-f", "docker-compose.yml", "-f", "docker-compose.prod.yml"])
    return command


def service_health(command: list[str]) -> dict[str, str]:
    result = subprocess.run(
        [*command, "ps", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout.strip()
    if not output:
        return {}
    rows = json.loads(output) if output.startswith("[") else [json.loads(line) for line in output.splitlines()]
    if isinstance(rows, dict):
        rows = [rows]
    return {row["Service"]: str(row.get("Health") or "").lower() for row in rows}


def wait_for_stack(command: list[str], timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        health = service_health(command)
        if all(health.get(service) == "healthy" for service in SERVICES):
            return
        if any(health.get(service) == "unhealthy" for service in SERVICES):
            raise SmokeFailure("A Compose service became unhealthy")
        time.sleep(5)
    raise SmokeFailure("Compose services did not become healthy before the timeout")


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout_s: int = 30,
) -> dict:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        content_type = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(base_url + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise SmokeFailure(f"{path} returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise SmokeFailure(f"{path} was unavailable") from None


def fixture_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(FIXTURE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(FIXTURE).as_posix())
    return buffer.getvalue()


def zip_form_data() -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    archive = fixture_zip()
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="upload"; filename="mini_fastapi.zip"\r\n'
        "Content-Type: application/zip\r\n\r\n"
    ).encode("ascii")
    return prefix + archive + f"\r\n--{boundary}--\r\n".encode("ascii"), f"multipart/form-data; boundary={boundary}"


def run_smoke(base_url: str, production: bool, timeout_s: int) -> None:
    command = compose_command(production)
    print("Building and starting the three-service stack...")
    subprocess.run([*command, "up", "-d", "--build"], cwd=ROOT, check=True)
    wait_for_stack(command, timeout_s)
    print("PostgreSQL, backend, and frontend are healthy.")

    password = secrets.token_urlsafe(24)
    email = f"prism-smoke-{uuid.uuid4().hex}@example.com"
    request_json(base_url, "/auth/register", method="POST", payload={"email": email, "password": password})
    login = request_json(base_url, "/auth/login", method="POST", payload={"email": email, "password": password})
    token = login.get("access_token")
    if not isinstance(token, str) or not token:
        raise SmokeFailure("Login did not return an access token")
    print("Registration and login passed.")

    models = request_json(base_url, "/models/config", token=token)
    slot = next((name for name, key in (("A", "model_a"), ("B", "model_b")) if models.get(key, {}).get("name")), None)
    if slot is None:
        raise SmokeFailure("No model slot is configured for the Q&A smoke test")

    body, content_type = zip_form_data()
    imported = request_json(
        base_url, "/repositories", method="POST", body=body,
        content_type=content_type, token=token, timeout_s=timeout_s,
    )
    repository_id = imported.get("repository_id")
    if not isinstance(repository_id, str):
        raise SmokeFailure("ZIP import did not return a repository ID")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = request_json(base_url, f"/repositories/{repository_id}/index-status", token=token)
        if status.get("state") == "READY":
            break
        if status.get("state") in {"FAILED", "PARTIAL"}:
            raise SmokeFailure("Fixture indexing did not reach READY")
        time.sleep(3)
    else:
        raise SmokeFailure("Fixture indexing did not reach READY before the timeout")
    print("Fixture ZIP import reached READY.")

    result = request_json(
        base_url, f"/repositories/{repository_id}/ask", method="POST",
        payload={"question": "What does create_access_token do?", "model_slot": slot},
        token=token, timeout_s=timeout_s,
    )
    answer = result.get("answer", {})
    evidence = answer.get("evidence", [])
    if not answer.get("answer") or not any(
        item.get("source_type") == "CODE"
        and item.get("repository_id") == repository_id
        and item.get("file_path")
        and isinstance(item.get("start_line"), int)
        and isinstance(item.get("end_line"), int)
        for item in evidence
    ):
        raise SmokeFailure("Q&A did not return a grounded repository answer")
    run_id = result.get("agent_run_id")
    trace = request_json(base_url, f"/agent-runs/{run_id}/trace", token=token)
    if not trace.get("model_executions") or not trace.get("tool_calls"):
        raise SmokeFailure("Q&A trace did not record tools and a model execution")
    print("Grounded Q&A and persisted trace passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true", help="Use the static frontend Compose override")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=900, help="Health and indexing timeout in seconds")
    args = parser.parse_args()
    try:
        run_smoke(args.base_url.rstrip("/"), args.production, args.timeout)
    except (SmokeFailure, subprocess.CalledProcessError, OSError, ValueError, KeyError) as exc:
        message = str(exc) if isinstance(exc, SmokeFailure) else type(exc).__name__
        print(f"FAIL: {message}", file=sys.stderr)
        return 1
    print("PASS: Docker Compose stack smoke test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
