from __future__ import annotations

import os
from pathlib import Path

# Определение базовой директории проекта и пути к файлу конфигурации окружения (.env)
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = BASE_DIR / ".env"


def load_environment() -> None:
    """
    Загружает переменные окружения из локального файла .env в os.environ.
    Предотвращает падение программы, если библиотека python-dotenv не установлена.
    """
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return

    load_dotenv(DEFAULT_ENV_PATH)


def get_required_env(name: str) -> str:
    """
    Возвращает значение обязательной переменной окружения.
    Если переменная не задана в .env, вызывает исключение RuntimeError, останавливающее сервер.
    """
    load_environment()
    value = os.getenv(name)
    if value:
        return value.strip()

    raise RuntimeError(
        f"{name} is not set. Add it to {DEFAULT_ENV_PATH.name} in the project root."
    )


def get_env(name: str, default: str) -> str:
    """
    Возвращает значение переменной окружения или дефолтное значение, если она отсутствует.
    """
    load_environment()
    return os.getenv(name, default).strip()

