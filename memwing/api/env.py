from __future__ import annotations

from dotenv import find_dotenv, load_dotenv


def load_app_env() -> None:
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)
        return
    load_dotenv(override=False)
