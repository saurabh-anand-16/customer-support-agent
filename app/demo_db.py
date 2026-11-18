"""
demo_db.py - the demo copy of the database.

The app never works on the real database. On first start the real file is copied to the demo path (config/agent.toml [app]).
"Reset demo data" copies the real file over the demo file again, so every order, return and review item is back as it was.
The real file is only ever read (copied from).
"""
import hashlib
import shutil
from pathlib import Path

from .config import AppSettings


class DemoDbError(RuntimeError):
    """The demo copy could not be made or reset. The message says why and names no customer data."""


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_paths(settings: AppSettings) -> None:
    if settings.source_db.resolve() == settings.demo_db.resolve():
        raise DemoDbError("The demo database path is the same as the real database path. Change [app].demo_db_path.")
    if not settings.source_db.is_file():
        raise DemoDbError(f"The real database was not found at {settings.source_db.name}. Build it with the scripts in the README.")


def ensure_demo_db(settings: AppSettings) -> Path:
    """Make the demo copy if it does not exist yet. Returns its path."""
    _check_paths(settings)
    if not settings.demo_db.is_file():
        settings.demo_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(settings.source_db, settings.demo_db)
    return settings.demo_db


def reset_demo_db(settings: AppSettings) -> Path:
    """Copy the real database over the demo copy. The caller must have let go of any open connection to the demo file first."""
    _check_paths(settings)
    settings.demo_db.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(settings.source_db, settings.demo_db)
    except OSError as err:
        raise DemoDbError(f"The demo data could not be reset ({type(err).__name__}).") from None
    return settings.demo_db
