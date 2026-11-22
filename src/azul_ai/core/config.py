import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE)


def get_required(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Set {name} in {ENV_FILE}.")
    return value
