import json
import logging
import os
from datetime import datetime

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def load_queue() -> list:
    settings = get_settings()
    if os.path.exists(settings.exception_queue_path):
        with open(settings.exception_queue_path) as f:
            return json.load(f)
    return []


def add_to_queue(message_id: str, result: dict) -> None:
    settings = get_settings()
    queue = load_queue()

    queue.append({
        'message_id': message_id,
        'timestamp': datetime.now().isoformat(),
        'subject': result['subject'],
        'sender': result['sender'],
        'confidence': result['confidence'],
        'signals': result['signals'],
        'body_preview': result['body_preview'],
        'status': 'pending_review',
    })

    os.makedirs(os.path.dirname(settings.exception_queue_path) or '.', exist_ok=True)
    with open(settings.exception_queue_path, 'w') as f:
        json.dump(queue, f, indent=2)

    logger.warning(
        "Added to exception queue: '%s' (%s%% confidence)",
        result['subject'],
        result['confidence'],
    )


def get_pending_reviews() -> list:
    return [e for e in load_queue() if e['status'] == 'pending_review']


def mark_reviewed(message_id: str, approved: bool) -> None:
    settings = get_settings()
    queue = load_queue()
    for item in queue:
        if item['message_id'] == message_id:
            item['status'] = 'approved' if approved else 'rejected'
            item['reviewed_at'] = datetime.now().isoformat()
    with open(settings.exception_queue_path, 'w') as f:
        json.dump(queue, f, indent=2)
