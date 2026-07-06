"""Register Gmail push notifications to Pub/Sub. Run from project root: python scripts/watch.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.core.config import get_settings
from app.core.keywords import SCOPES

settings = get_settings()


def setup_gmail_watch() -> None:
    try:
        print('Loading credentials...')
        creds = Credentials.from_authorized_user_file(settings.gmail_token_path, SCOPES)

        if creds.expired and creds.refresh_token:
            print('Refreshing token...')
            creds.refresh(Request())

        print('Connecting to Gmail API...')
        service = build('gmail', 'v1', credentials=creds)

        request_body = {
            'labelIds': ['INBOX'],
            'topicName': settings.pubsub_topic,
            'labelFilterBehavior': 'INCLUDE',
        }

        print('Setting up Gmail watch...')
        result = service.users().watch(userId='me', body=request_body).execute()

        print('Watch set up successfully!')
        print(f'History ID : {result["historyId"]}')
        print(f'Expiration : {result["expiration"]}')

    except Exception as e:
        print(f'Error: {e}')


if __name__ == '__main__':
    setup_gmail_watch()
