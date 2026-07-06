"""One-time Gmail OAuth setup. Run from project root: python scripts/auth.py"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_auth_oauthlib.flow import InstalledAppFlow

from app.core.config import get_settings
from app.core.keywords import SCOPES

settings = get_settings()
os.makedirs(os.path.dirname(settings.gmail_token_path) or '.', exist_ok=True)

flow = InstalledAppFlow.from_client_secrets_file(settings.gmail_credentials_path, SCOPES)

creds = flow.run_local_server(
    port=3000,
    access_type='offline',
    prompt='consent',
)

with open(settings.gmail_token_path, 'w') as f:
    f.write(creds.to_json())

print(f'Authorization successful! Token saved to {settings.gmail_token_path}')

with open(settings.gmail_token_path) as f:
    data = json.load(f)
    if 'refresh_token' in data:
        print('refresh_token found — you are good to go!')
    else:
        print('refresh_token still missing — try again')
