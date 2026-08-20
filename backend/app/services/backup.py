"""Database backup and restore.

WHAT MAKES THIS SAFE
--------------------
1. The command is built as an argument list, never a shell string, and
   `shell=False` always. There is no interpolation of caller input into a
   command anywhere in this module.
2. The only caller-supplied value that reaches the filesystem is a backup
   *id* — an integer row in the registry. The filename comes from the row,
   and is re-validated against a strict pattern before use, so even a
   corrupted registry cannot produce a traversal.
3. The database password is passed through the environment (PGPASSWORD),
   never on a command line where it would show up in a process list.
4. Restore refuses to run against the live database unless it is explicitly
   enabled, so a test or a stray call cannot destroy a developer's data.

A backup is not successful because a file exists. `verify` checks the file
is present, non-empty, and starts with the bytes pg_dump actually writes.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..config import settings
from .secrets import redact

#: Where dumps live. Overridable by environment for a real deployment.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/var/backups/jgoldai"))

#: Generated server-side and re-validated before any filesystem use.
FILENAME_RE = re.compile(r"^jgoldai-\d{8}-\d{6}\.dump$")

#: Custom-format pg_dump archives start with "PGDMP".
_MAGIC = b"PGDMP"

#: Restoring overwrites a database. Off unless a deployment opts in.
RESTORE_ENABLED = os.environ.get("ALLOW_DB_RESTORE", "").lower() in ("1", "true", "yes")


class BackupError(Exception):
    """Backup or restore failed. The message is already redacted."""


@dataclass(frozen=True, slots=True)
class BackupOutcome:
    ok: bool
    filename: str
    size_bytes: int
    detail: str
    #: SHA-256 of the artefact, when one was produced.
    checksum: str = ""


def checksum_of(path: Path) -> str:
    """Streamed, so a large dump does not have to fit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_name() -> str:
    """The database name alone. Never the DSN, never credentials."""
    url = urlparse(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"))
    return (url.path or "/").lstrip("/") or "postgres"


def new_filename(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"jgoldai-{now:%Y%m%d-%H%M%S}.dump"


def safe_path(filename: str) -> Path:
    """Resolve a registry filename to a path, or refuse.

    Rejects anything that is not the exact generated shape, then confirms
    the resolved path is still inside BACKUP_DIR — so a name that somehow
    passed the pattern still cannot escape the directory.
    """
    if not FILENAME_RE.match(filename or ""):
        raise BackupError("Not a valid backup name.")
    resolved = (BACKUP_DIR / filename).resolve()
    root = BACKUP_DIR.resolve()
    if root not in resolved.parents:
        raise BackupError("Backup path resolved outside the backup directory.")
    return resolved


def _dsn_parts() -> tuple[list[str], dict[str, str]]:
    """Connection arguments and environment, with the password never in argv."""
    url = urlparse(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"))
    args = []
    if url.hostname:
        args += ["-h", url.hostname]
    if url.port:
        args += ["-p", str(url.port)]
    if url.username:
        args += ["-U", unquote(url.username)]
    database = (url.path or "/").lstrip("/") or "postgres"
    env = dict(os.environ)
    if url.password:
        # Environment, not argv: a command line is visible in a process list.
        env["PGPASSWORD"] = unquote(url.password)
    return args + [database], env


async def _run(argv: list[str], env: dict[str, str]) -> tuple[int, str]:
    """Run a predefined argument list. shell=False, always."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    _, err = await proc.communicate()
    # Redacted before it can reach a log, a record or a response.
    return proc.returncode or 0, redact(err.decode("utf-8", "replace"))[:500]


async def create(filename: str | None = None) -> BackupOutcome:
    """Take a dump. Returns an outcome; raises only on programmer error."""
    name = filename or new_filename()
    target = safe_path(name)
    target.parent.mkdir(parents=True, exist_ok=True)

    conn_args, env = _dsn_parts()
    argv = ["pg_dump", "--format=custom", "--file", str(target), *conn_args]

    try:
        code, err = await _run(argv, env)
    except FileNotFoundError:
        return BackupOutcome(False, name, 0, "pg_dump is not installed on this host.")
    except Exception as exc:  # noqa: BLE001 - reported, never raised outward
        return BackupOutcome(False, name, 0, redact(exc)[:300])

    if code != 0:
        return BackupOutcome(False, name, 0, err or "pg_dump reported a failure.")

    size = target.stat().st_size if target.exists() else 0
    if size == 0:
        return BackupOutcome(False, name, 0, "pg_dump produced an empty file.")
    return BackupOutcome(True, name, size, "Backup written.", checksum_of(target))


def verify(filename: str) -> BackupOutcome:
    """A file existing is not a backup. Check it looks like one."""
    try:
        path = safe_path(filename)
    except BackupError as exc:
        return BackupOutcome(False, filename, 0, str(exc))

    if not path.exists():
        return BackupOutcome(False, filename, 0, "Backup file is missing.")
    size = path.stat().st_size
    if size == 0:
        return BackupOutcome(False, filename, 0, "Backup file is empty.")
    with path.open("rb") as fh:
        magic = fh.read(len(_MAGIC))
    if magic != _MAGIC:
        return BackupOutcome(
            False, filename, size, "File is not a PostgreSQL custom-format dump."
        )
    return BackupOutcome(True, filename, size, "Backup verified.", checksum_of(path))


def verify_against(filename: str, expected_checksum: str) -> BackupOutcome:
    """Verify, and prove the bytes are the ones originally written.

    Presence and format say the file is a dump. Only the checksum says it is
    *this* dump, unmodified since it was taken.
    """
    result = verify(filename)
    if not result.ok or not expected_checksum:
        return result
    if result.checksum != expected_checksum:
        return BackupOutcome(
            False, filename, result.size_bytes,
            "Checksum does not match the value recorded when the backup was "
            "taken; the file has changed.",
            result.checksum,
        )
    return result


async def restore(filename: str, *, confirmed: bool) -> BackupOutcome:
    """Restore a registered backup. Refuses unless explicitly enabled.

    `confirmed` is not a formality: without it this returns without touching
    anything, so a mis-wired call or a test cannot overwrite a database.
    """
    if not confirmed:
        return BackupOutcome(False, filename, 0, "Restore was not confirmed.")
    if not RESTORE_ENABLED:
        return BackupOutcome(
            False,
            filename,
            0,
            "Restore is disabled on this host. Set ALLOW_DB_RESTORE=true to "
            "enable it, and only on a host where overwriting the database is "
            "intended.",
        )

    checked = verify(filename)
    if not checked.ok:
        return BackupOutcome(False, filename, 0, f"Refused: {checked.detail}")

    path = safe_path(filename)
    conn_args, env = _dsn_parts()
    argv = ["pg_restore", "--clean", "--if-exists", "--no-owner",
            "--dbname", conn_args[-1], *conn_args[:-1], str(path)]
    try:
        code, err = await _run(argv, env)
    except FileNotFoundError:
        return BackupOutcome(False, filename, 0, "pg_restore is not installed.")
    if code != 0:
        return BackupOutcome(False, filename, 0, err or "pg_restore failed.")
    return BackupOutcome(True, filename, checked.size_bytes, "Restore completed.")


def apply_retention(keep: int | None = None) -> list[str]:
    """Delete all but the newest `keep` dumps. Returns what was removed.

    Only files matching the generated pattern are ever considered, so a
    stray file in the directory is left alone rather than deleted.
    """
    keep = keep if keep is not None else int(os.environ.get("BACKUP_RETENTION", "7"))
    if not BACKUP_DIR.exists():
        return []
    dumps = sorted(
        (p for p in BACKUP_DIR.iterdir() if FILENAME_RE.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )
    removed = []
    for path in dumps[keep:]:
        path.unlink(missing_ok=True)
        removed.append(path.name)
    return removed
