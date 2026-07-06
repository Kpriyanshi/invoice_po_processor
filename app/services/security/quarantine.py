import json
import logging
import os
from datetime import datetime

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _load_quarantine() -> list:
    settings = get_settings()
    if os.path.exists(settings.quarantine_path):
        with open(settings.quarantine_path) as f:
            return json.load(f)
    return []


def log_rejection(
    message_id: str,
    filename: str,
    sender: str,
    subject: str,
    reason: str,
    detected_mime: str | None = None,
    threat_name: str | None = None,
) -> None:
    settings = get_settings()
    record = {
        'message_id': message_id,
        'filename': filename,
        'sender': sender,
        'subject': subject,
        'reason': reason,
        'detected_mime': detected_mime,
        'threat_name': threat_name,
        'timestamp': datetime.now().isoformat(),
    }

    quarantine = _load_quarantine()
    quarantine.append(record)

    os.makedirs(os.path.dirname(settings.quarantine_path) or '.', exist_ok=True)
    with open(settings.quarantine_path, 'w') as f:
        json.dump(quarantine, f, indent=2)

    logger.warning(
        'Attachment quarantined | message_id=%s file=%s reason=%s threat=%s',
        message_id,
        filename,
        reason,
        threat_name,
    )
