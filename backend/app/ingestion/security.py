import ntpath
import stat
import zipfile
from pathlib import Path, PurePosixPath

from app.config import get_settings


class ZipSafetyError(ValueError):
    def __init__(self, reason: str, *, limit_exceeded: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.limit_exceeded = limit_exceeded


def _validated_relative_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or ntpath.splitdrive(normalized)[0]:
        raise ZipSafetyError(f"Archive entry has an absolute path: {name}")
    if ".." in path.parts:
        raise ZipSafetyError(f"Archive entry contains a parent path segment: {name}")
    return path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_IFMT(mode) == stat.S_IFLNK


def safe_extract(zip_path: str | Path, dest_dir: str | Path) -> None:
    settings = get_settings()
    archive_path = Path(zip_path)
    destination = Path(dest_dir).resolve()
    zip_limit = settings.max_zip_size_mb * 1024 * 1024
    extracted_limit = settings.max_extracted_size_mb * 1024 * 1024

    if archive_path.stat().st_size > zip_limit:
        raise ZipSafetyError(
            f"ZIP exceeds the {settings.max_zip_size_mb} MB limit",
            limit_exceeded=True,
        )

    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            file_entries = [entry for entry in entries if not entry.is_dir()]
            if len(file_entries) > settings.max_extracted_files:
                raise ZipSafetyError(
                    f"Archive exceeds the {settings.max_extracted_files} file limit",
                    limit_exceeded=True,
                )
            total_size = sum(entry.file_size for entry in file_entries)
            if total_size > extracted_limit:
                raise ZipSafetyError(
                    f"Extracted content exceeds the {settings.max_extracted_size_mb} MB limit",
                    limit_exceeded=True,
                )

            validated: list[tuple[zipfile.ZipInfo, Path]] = []
            for entry in entries:
                relative_path = _validated_relative_path(entry.filename)
                if _is_symlink(entry):
                    raise ZipSafetyError(
                        f"Archive entry is a symbolic link: {entry.filename}"
                    )
                target = (destination / Path(*relative_path.parts)).resolve()
                if not target.is_relative_to(destination):
                    raise ZipSafetyError(
                        f"Archive entry resolves outside the extraction root: {entry.filename}"
                    )
                validated.append((entry, target))

            destination.mkdir(parents=True, exist_ok=True)
            for entry, target in validated:
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
    except zipfile.BadZipFile as exc:
        raise ZipSafetyError("Uploaded file is not a valid ZIP archive") from exc
