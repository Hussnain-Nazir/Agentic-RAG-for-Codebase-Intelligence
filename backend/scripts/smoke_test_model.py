# Manual-only real model smoke test. Automated tests must never invoke this script.
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.llm.base import Message
from app.llm.factory import get_model_a, get_model_b


async def run(slot: str) -> None:
    settings = get_settings()
    provider = get_model_a() if slot == "a" else get_model_b()
    timeout_s = (
        settings.model_a_timeout if slot == "a" else settings.model_b_timeout
    )
    result = await provider.complete(
        messages=[
            Message(
                role="user",
                content="Reply with a short model connectivity confirmation.",
            )
        ],
        schema=None,
        timeout_s=timeout_s,
    )
    print(json.dumps(result.raw_response, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manually test one configured model slot")
    parser.add_argument("slot", choices=("a", "b"))
    args = parser.parse_args()
    asyncio.run(run(args.slot))


if __name__ == "__main__":
    main()
