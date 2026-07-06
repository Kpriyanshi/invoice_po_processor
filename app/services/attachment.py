import base64
import logging
import os
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.services.gmail_client import get_gmail_service
from app.services.security.malware_scanner import scan_bytes
from app.services.security.mime_validator import validate_attachment
from app.services.security.quarantine import log_rejection

logger = logging.getLogger(__name__)


@dataclass
class AttachmentSaveResult:
    saved_paths: list[str] = field(default_factory=list)
    rejected_count: int = 0
    attempted_count: int = 0


def save_attachments(
    message_id: str,
    payload: dict,
    subject: str,
    sender: str = '',
) -> AttachmentSaveResult:
    """Download, validate, scan, and save invoice attachments."""
    settings = get_settings()
    result = AttachmentSaveResult()
    os.makedirs(settings.invoice_save_folder, exist_ok=True)

    if 'parts' not in payload:
        return result

    service = get_gmail_service()

    for part in payload['parts']:
        filename = part.get('filename', '')
        body = part.get('body', {})
        attachment_id = body.get('attachmentId')

        if not filename or not attachment_id:
            continue

        result.attempted_count += 1

        attachment = service.users().messages().attachments().get(
            userId='me',
            messageId=message_id,
            id=attachment_id,
        ).execute()

        file_data = base64.urlsafe_b64decode(attachment['data'])

        mime_result = validate_attachment(filename, file_data)
        if not mime_result.valid:
            log_rejection(
                message_id=message_id,
                filename=filename,
                sender=sender,
                subject=subject,
                reason=mime_result.reason or 'mime_validation_failed',
                detected_mime=mime_result.detected_mime,
            )
            result.rejected_count += 1
            continue

        scan_result = scan_bytes(file_data)
        if not scan_result.clean:
            log_rejection(
                message_id=message_id,
                filename=filename,
                sender=sender,
                subject=subject,
                reason=scan_result.reason or 'malware_detected',
                detected_mime=mime_result.detected_mime,
                threat_name=scan_result.threat_name,
            )
            result.rejected_count += 1
            continue

        safe_subject = ''.join(c for c in subject if c.isalnum() or c in ' -_')[:40]
        save_name = f'{safe_subject}_{filename}'
        save_path = os.path.join(settings.invoice_save_folder, save_name)

        with open(save_path, 'wb') as f:
            f.write(file_data)

        result.saved_paths.append(save_path)
        logger.info('Saved attachment: %s (mime=%s)', save_path, mime_result.detected_mime)

    return result
