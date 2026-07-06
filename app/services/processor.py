import logging

from googleapiclient.errors import HttpError

from app.core.config import get_settings
from app.services.attachment import save_attachments
from app.services.classifier import classify_email
from app.services.exception_queue import add_to_queue
from app.services.gmail_client import (
    get_gmail_service,
    get_last_history_id,
    load_processed_ids,
    save_last_history_id,
    save_processed_id,
)

logger = logging.getLogger(__name__)


def process_gmail_notification(history_id: str) -> None:
    settings = get_settings()

    if history_id in load_processed_ids():
        logger.debug('Skipping duplicate history_id: %s', history_id)
        return

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
        return

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
                            }
                            add_to_queue(msg_id, security_result)

                elif result['verdict'] == 'exception_queue':
                    logger.warning(
                        'EXCEPTION QUEUE — confidence %s%% < %s%%',
                        result['confidence'],
                        settings.confidence_threshold,
                    )
                    add_to_queue(msg_id, result)

                else:
                    logger.info(
                        'SKIP — confidence %s%% (not an invoice)',
                        result['confidence'],
                    )

            except HttpError:
                logger.warning('Message %s not found — skipping', msg_id)
                continue

    save_last_history_id(history_id)
