import logging

from googleapiclient.errors import HttpError

from app.core.config import get_settings
from app.services.attachment import save_attachments
from app.services.classifier import classify_email
from app.services.exception_case import ExceptionCategory, ExceptionRootCause
from app.services.exception_queue import add_to_queue
from app.services.gmail_client import (
    get_gmail_service,
    get_last_history_id,
    load_processed_ids,
    save_last_history_id,
    save_processed_id,
)
from app.services.ocr.vision_service import OcrJob, is_ocr_supported

logger = logging.getLogger(__name__)


def process_gmail_notification(history_id: str) -> list[OcrJob]:
    """
    Classify new Gmail messages, save invoice attachments, and return OCR jobs
    for background processing after the webhook acks Pub/Sub.
    """
    settings = get_settings()
    ocr_jobs: list[OcrJob] = []

    if history_id in load_processed_ids():
        logger.debug('Skipping duplicate history_id: %s', history_id)
        return ocr_jobs

    save_processed_id(history_id)

    service = get_gmail_service()
    last_id = get_last_history_id() or history_id

    try:
        history = service.users().history().list(
            userId='me',
            startHistoryId=last_id,
            historyTypes=['messageAdded'],
        ).execute()
    except HttpError:
        save_last_history_id(history_id)
        return ocr_jobs

    for change in history.get('history', []):
        for msg in change.get('messagesAdded', []):
            msg_id = msg['message']['id']
            try:
                message = service.users().messages().get(
                    userId='me', id=msg_id, format='full',
                ).execute()

                result = classify_email(message)

                logger.info(
                    'Email classified | from=%s subject=%s confidence=%s%% signals=%s',
                    result['sender'],
                    result['subject'],
                    result['confidence'],
                    ', '.join(result['signals']) or 'none',
                )

                if result['verdict'] == 'store':
                    logger.info(
                        'STORE — confidence %s%% >= %s%%',
                        result['confidence'],
                        settings.confidence_threshold,
                    )
                    if result['attachments']:
                        save_result = save_attachments(
                            msg_id,
                            message['payload'],
                            result['subject'],
                            sender=result['sender'],
                        )
                        if (
                            save_result.attempted_count > 0
                            and save_result.rejected_count == save_result.attempted_count
                        ):
                            logger.warning(
                                'All attachments rejected by security — routing to exception queue'
                            )
                            security_result = {
                                **result,
                                'signals': result['signals'] + ['security: all attachments rejected'],
                                'category': ExceptionCategory.SECURITY.value,
                                'root_cause': ExceptionRootCause.SECURITY_ALL_ATTACHMENTS_REJECTED.value,
                                'reason': (
                                    'Rejected for further processing — all attachments '
                                    'failed security checks (MIME/ClamAV).'
                                ),
                            }
                            add_to_queue(msg_id, security_result)
                        else:
                            for path in save_result.saved_paths:
                                if is_ocr_supported(path):
                                    ocr_jobs.append(
                                        OcrJob(
                                            path=path,
                                            message_id=msg_id,
                                            subject=result['subject'],
                                            sender=result['sender'],
                                        )
                                    )
                                else:
                                    logger.info(
                                        'Saved non-OCR attachment (no vision job): %s',
                                        path,
                                    )

                elif result['verdict'] == 'exception_queue':
                    logger.warning(
                        'EXCEPTION QUEUE — confidence %s%% < %s%%',
                        result['confidence'],
                        settings.confidence_threshold,
                    )
                    add_to_queue(
                        msg_id,
                        {
                            **result,
                            'category': ExceptionCategory.CLASSIFICATION.value,
                            'root_cause': ExceptionRootCause.CLASSIFICATION_LOW_CONFIDENCE.value,
                            'reason': (
                                f'Rejected for further processing — classification confidence '
                                f'{result["confidence"]}% below threshold '
                                f'{settings.confidence_threshold}%.'
                            ),
                        },
                    )

                else:
                    logger.info(
                        'SKIP — confidence %s%% (not an invoice)',
                        result['confidence'],
                    )

            except HttpError:
                logger.warning('Message %s not found — skipping', msg_id)
                continue

    save_last_history_id(history_id)
    return ocr_jobs
