import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_local_env(path: Path = ENV_PATH) -> None:
    load_dotenv(path)


load_local_env()


def _streamlit_secret(name: str) -> Optional[str]:
    try:
        import streamlit as st

        value = st.secrets.get(name)
        return str(value) if value else None
    except Exception:
        return None


def get_config_value(name: str) -> Optional[str]:
    return os.getenv(name) or _streamlit_secret(name)


OPENAI_API_KEY = get_config_value("OPENAI_API_KEY")
FMP_API_KEY = get_config_value("FMP_API_KEY")
