from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = BASE_DIR / ".env"


def load_environment() -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return

    load_dotenv(DEFAULT_ENV_PATH)


def get_required_env(name: str) -> str:
    load_environment()
    value = os.getenv(name)
    if value:
        return value.strip()

    raise RuntimeError(
        f"{name} is not set. Add it to {DEFAULT_ENV_PATH.name} in the project root."
    )


def get_env(name: str, default: str) -> str:
    load_environment()
    return os.getenv(name, default).strip()
