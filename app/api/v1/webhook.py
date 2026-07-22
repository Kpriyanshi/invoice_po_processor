import base64
import json
import logging

from fastapi import APIRouter, BackgroundTasks

from app.schemas.pubsub import PubSubEnvelope, StatusResponse
from app.services.ocr.vision_service import run_vision_ocr_job
from app.services.processor import process_gmail_notification

logger = logging.getLogger(__name__)

router = APIRouter(tags=['webhook'])


@router.post('/webhook', response_model=StatusResponse)
def webhook(
    background_tasks: BackgroundTasks,
    envelope: PubSubEnvelope | None = None,
) -> StatusResponse:
    try:
        if not envelope or not envelope.message or not envelope.message.data:
            # Empty/test POSTs (e.g. Body "{}") — ack without processing
            return StatusResponse(status='ok')

        raw = base64.b64decode(envelope.message.data).decode('utf-8').strip()
        if not raw:
            return StatusResponse(status='ok')

        notification = json.loads(raw)
        history_id = notification.get('historyId')
        if not history_id:
            logger.warning('Pub/Sub message missing historyId: %s', notification)
            return StatusResponse(status='ok')

        ocr_jobs = process_gmail_notification(str(history_id))
        for job in ocr_jobs:
            background_tasks.add_task(
                run_vision_ocr_job,
                job.path,
                message_id=job.message_id,
                subject=job.subject,
                sender=job.sender,
            )
            logger.info(
                'Scheduled vision OCR | message_id=%s file=%s',
                job.message_id,
                job.path,
            )

    except Exception as e:
        logger.exception('Webhook error: %s', e)

    return StatusResponse(status='ok')
