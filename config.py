from dotenv import load_dotenv
import os
from pathlib import Path
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = PROJECT_ROOT / "cache"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")


def _get_secret(name):
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st

        return st.secrets.get(name)
    except Exception:
        return None


OPENAI_API_KEY = _get_secret("OPENAI_API_KEY")
FMP_API_KEY = _get_secret("FMP_API_KEY")


def get_openai_client():
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set. Please configure it in .env.")
    return OpenAI(api_key=OPENAI_API_KEY)


def get_fmp_api_key():
    if not FMP_API_KEY:
        raise ValueError("FMP_API_KEY is not set. Please configure it in .env.")
    return FMP_API_KEY
