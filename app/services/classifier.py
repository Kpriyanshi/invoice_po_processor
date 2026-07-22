import base64

from app.core.config import get_settings
from app.core.keywords import (
    BODY_KEYWORDS,
    INVOICE_ATTACHMENT_TYPES,
    SUBJECT_KEYWORDS,
)

_FILENAME_KEYWORDS = ('invoice', 'tax', 'bill', 'gst', 'inv')


def score_subject(subject: str) -> tuple[int, list]:
    subject_lower = subject.lower()
    score = 0
    signals = []

    for keyword, weight in SUBJECT_KEYWORDS.items():
        if keyword in subject_lower:
            score += weight
            signals.append(f"subject: '{keyword}'")

    return min(score, 50), signals


def score_body(body: str) -> tuple[int, list]:
    body_lower = body.lower()
    score = 0
    signals = []

    for keyword, weight in BODY_KEYWORDS.items():
        if keyword in body_lower:
            score += weight
            signals.append(f"body: '{keyword}'")

    return min(score, 40), signals


def score_attachments(attachments: list) -> tuple[int, list]:
    score = 0
    signals = []

    for filename in attachments:
        name_lower = filename.lower()
        ext = '.' + filename.split('.')[-1].lower() if '.' in filename else ''
        if ext in INVOICE_ATTACHMENT_TYPES:
            score += INVOICE_ATTACHMENT_TYPES[ext]
            signals.append(f"attachment: '{filename}' ({ext})")
        for kw in _FILENAME_KEYWORDS:
            if kw in name_lower:
                score += 15
                signals.append(f"attachment-name: '{kw}' in '{filename}'")
                break

    return min(score, 35), signals


def get_email_body(payload: dict) -> str:
    body = ''

    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain':
                data = part['body'].get('data', '')
                if data:
                    body += base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            elif 'parts' in part:
                for subpart in part['parts']:
                    if subpart.get('mimeType') == 'text/plain':
                        data = subpart['body'].get('data', '')
                        if data:
                            body += base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    else:
        data = payload.get('body', {}).get('data', '')
        if data:
            body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

    return body


def get_attachments(payload: dict) -> list:
    attachments: list[str] = []

    def walk(part: dict) -> None:
        filename = part.get('filename') or ''
        if filename:
            attachments.append(filename)
        for child in part.get('parts') or []:
            walk(child)

    walk(payload)
    return attachments


def classify_email(message: dict) -> dict:
    settings = get_settings()
    headers = message['payload']['headers']
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
    sender = next((h['value'] for h in headers if h['name'] == 'From'), '')

    body = get_email_body(message['payload'])
    attachments = get_attachments(message['payload'])

    subject_score, subject_signals = score_subject(subject)
    body_score, body_signals = score_body(body)
    attach_score, attach_signals = score_attachments(attachments)

    confidence = min(subject_score + body_score + attach_score, 100)
    all_signals = subject_signals + body_signals + attach_signals

    if confidence >= settings.confidence_threshold:
        verdict = 'store'
    elif confidence >= 40:
        verdict = 'exception_queue'
    else:
        verdict = 'skip'

    return {
        'subject': subject,
        'sender': sender,
        'confidence': confidence,
        'verdict': verdict,
        'signals': all_signals,
        'attachments': attachments,
        'body_preview': body[:200] + '...' if len(body) > 200 else body,
    }
