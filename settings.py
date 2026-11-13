"""Settings entered on the setup page, kept in the usual per-user settings folder."""
import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv, set_key, unset_key


def folder() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.getenv("APPDATA") or Path.home())
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "Recipe Digester"


def path() -> Path:
    return folder() / "settings.env"


def load() -> None:
    """A .env next to the code is read first and wins, so developers can keep using it."""
    load_dotenv(Path(__file__).parent / ".env")
    load_dotenv(path())


def save(values: dict[str, str]) -> None:
    """Store the given settings; an empty value removes that setting."""
    path().parent.mkdir(parents=True, exist_ok=True)
    path().touch(mode=0o600, exist_ok=True)
    stored = dotenv_values(path())
    for key, value in values.items():
        if value:
            set_key(path(), key, value)
            os.environ[key] = value
        elif key in stored:
            unset_key(path(), key)
            os.environ.pop(key, None)
