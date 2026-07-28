import json
import logging
import os
import uuid
from datetime import datetime

from app.core.config import get_settings
from app.services.exception_case import infer_exception_tags

logger = logging.getLogger(__name__)


def load_queue() -> list:
    settings = get_settings()
    if os.path.exists(settings.exception_queue_path):
        with open(settings.exception_queue_path) as f:
            return json.load(f)
    return []


def add_to_queue(message_id: str, result: dict) -> str:
    """
    Create a structured exception case and append to the review queue.
    Returns the new case_id.
    """
    settings = get_settings()
    queue = load_queue()

    signals = result.get('signals') or []
    reason = result.get('reason') or ('; '.join(signals) if signals else 'pending_review')

    category = result.get('category')
    root_cause = result.get('root_cause')
    if not category or not root_cause:
        inferred_category, inferred_root = infer_exception_tags(signals, reason)
        category = category or inferred_category
        root_cause = root_cause or inferred_root

    case_id = str(uuid.uuid4())
    case = {
        'case_id': case_id,
        'message_id': message_id,
        'timestamp': datetime.now().isoformat(),
        'category': category,
        'root_cause': root_cause,
        'subject': result.get('subject', ''),
        'sender': result.get('sender', ''),
        'confidence': result.get('confidence', 0),
        'signals': signals,
        'reason': reason,
        'body_preview': result.get('body_preview', ''),
        'status': 'pending_review',
    }
    queue.append(case)

    os.makedirs(os.path.dirname(settings.exception_queue_path) or '.', exist_ok=True)
    with open(settings.exception_queue_path, 'w') as f:
        json.dump(queue, f, indent=2)

    logger.warning(
        "Exception case %s | category=%s root_cause=%s subject='%s' (%s%%)",
        case_id,
        category,
        root_cause,
        result.get('subject', ''),
        result.get('confidence', 0),
    )
    return case_id


def get_pending_reviews() -> list:
    return [e for e in load_queue() if e['status'] == 'pending_review']


def mark_reviewed(case_id: str, approved: bool) -> bool:
    """
    Mark an exception case by case_id.
    Returns True if a matching case was updated.
    """
    settings = get_settings()
    queue = load_queue()
    found = False
    for item in queue:
        if item.get('case_id') == case_id:
            item['status'] = 'approved' if approved else 'rejected'
            item['reviewed_at'] = datetime.now().isoformat()
            found = True
            break

    if found:
        with open(settings.exception_queue_path, 'w') as f:
            json.dump(queue, f, indent=2)
    return found
