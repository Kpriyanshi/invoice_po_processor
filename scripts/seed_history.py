"""Seed last_history_id.json from Gmail profile. Run from project root: python scripts/seed_history.py"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.core.config import get_settings
from app.core.keywords import SCOPES

settings = get_settings()

creds = Credentials.from_authorized_user_file(settings.gmail_token_path, SCOPES)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())

service = build('gmail', 'v1', credentials=creds)

profile = service.users().getProfile(userId='me').execute()
history_id = profile['historyId']

print(f'Current History ID: {history_id}')

os.makedirs(os.path.dirname(settings.last_history_id_path) or '.', exist_ok=True)
with open(settings.last_history_id_path, 'w') as f:
    json.dump({'historyId': str(history_id)}, f)

print(f'Saved to {settings.last_history_id_path}!')
