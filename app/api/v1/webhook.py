import base64
import json
import logging

from fastapi import APIRouter

from app.schemas.pubsub import PubSubEnvelope, StatusResponse
from app.services.processor import process_gmail_notification

logger = logging.getLogger(__name__)

router = APIRouter(tags=['webhook'])


@router.post('/webhook', response_model=StatusResponse)
def webhook(envelope: PubSubEnvelope | None = None) -> StatusResponse:
    try:
        if not envelope:
            return StatusResponse(status='ok')

        pubsub_message = envelope.message
        data = base64.b64decode(pubsub_message.data).decode('utf-8')
        notification = json.loads(data)
        history_id = str(notification.get('historyId'))

        process_gmail_notification(history_id)

    except Exception as e:
        logger.exception('Webhook error: %s', e)

    return StatusResponse(status='ok')
