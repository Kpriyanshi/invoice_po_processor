import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.core.config import get_settings
from app.core.keywords import SCOPES


def get_gmail_service():
    settings = get_settings()
    creds = Credentials.from_authorized_user_file(settings.gmail_token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)


def load_processed_ids() -> set[str]:
    settings = get_settings()
    if os.path.exists(settings.processed_ids_path):
        with open(settings.processed_ids_path) as f:
            return set(json.load(f))
    return set()


def save_processed_id(history_id: str) -> None:
    settings = get_settings()
    ids = load_processed_ids()
    ids.add(str(history_id))
    ids = set(list(ids)[-100:])
    os.makedirs(os.path.dirname(settings.processed_ids_path) or '.', exist_ok=True)
    with open(settings.processed_ids_path, 'w') as f:
        json.dump(list(ids), f)


def get_last_history_id() -> str | None:
    settings = get_settings()
    if os.path.exists(settings.last_history_id_path):
        with open(settings.last_history_id_path) as f:
            return json.load(f).get('historyId')
    return None


def save_last_history_id(history_id: str) -> None:
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.last_history_id_path) or '.', exist_ok=True)
    with open(settings.last_history_id_path, 'w') as f:
        json.dump({'historyId': str(history_id)}, f)
