from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.services.exception_queue import add_to_queue

logger = logging.getLogger(__name__)

# Match ocr_module.preprocessing supported types (PDF + images).
_OCR_SUFFIXES = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp'}


@dataclass(frozen=True)
class OcrJob:
    path: str
    message_id: str
    subject: str
    sender: str


def is_ocr_supported(path: str) -> bool:
    return Path(path).suffix.lower() in _OCR_SUFFIXES


def extraction_output_path(pdf_path: str, output_dir: str | None = None) -> str:
    settings = get_settings()
    out_dir = output_dir or settings.ocr_output_dir
    base = os.path.basename(pdf_path).replace('\\', '_').replace('/', '_')
    return os.path.join(out_dir, f'{base}.json')


def _queue_ocr_issue(
    *,
    message_id: str,
    subject: str,
    sender: str,
    signal: str,
    body_preview: str = '',
    confidence: int = 0,
) -> None:
    add_to_queue(
        message_id,
        {
            'subject': subject,
            'sender': sender,
            'confidence': confidence,
            'signals': [signal],
            'body_preview': body_preview,
        },
    )


async def _extract_async(file_path: str):
    from ocr_module import GPT4VisionOCR, OCRSettings

    settings = OCRSettings()
    ocr = GPT4VisionOCR(settings)
    return await ocr.extract(file_path, raise_on_low_confidence=True)


def run_vision_ocr_job(
    pdf_path: str,
    *,
    message_id: str = '',
    subject: str = '',
    sender: str = '',
) -> str | None:
    """
    Sync entry point for FastAPI BackgroundTasks.
    Returns output JSON path on success, None if skipped/failed.
    """
    settings = get_settings()

    if not settings.ocr_enabled:
        logger.info('OCR disabled — skipping %s', pdf_path)
        return None

    if not is_ocr_supported(pdf_path):
        logger.info('OCR skipped (unsupported type): %s', pdf_path)
        return None

    if not os.path.isfile(pdf_path):
        logger.error('OCR skipped — file missing: %s', pdf_path)
        return None

    out_path = extraction_output_path(pdf_path)
    if os.path.isfile(out_path):
        logger.info('OCR idempotent skip — already extracted: %s', out_path)
        return out_path

    try:
        from ocr_module import OCRSettings
        from ocr_module.exceptions import LowConfidenceError, VisionAPIError
    except ImportError as e:
        logger.exception('ocr_module not installed: %s', e)
        _queue_ocr_issue(
            message_id=message_id or 'unknown',
            subject=subject or os.path.basename(pdf_path),
            sender=sender,
            signal=f'ocr: module_import_failed: {e}',
            body_preview=pdf_path,
        )
        return None

    ocr_settings = OCRSettings()
    if not ocr_settings.openai_api_key:
        env_path = OCRSettings.env_file_path()
        logger.warning(
            'OCR_OPENAI_API_KEY missing in %s — skipping vision OCR for %s. '
            'Set OCR_OPENAI_API_KEY in the project-root .env (not ocr_module/.env), save the file, then retry.',
            env_path,
            pdf_path,
        )
        return None

    try:
        result = asyncio.run(_extract_async(pdf_path))
    except LowConfidenceError as e:
        logger.warning(
            'OCR low confidence | message_id=%s file=%s error=%s',
            message_id,
            pdf_path,
            e,
        )
        _queue_ocr_issue(
            message_id=message_id or 'unknown',
            subject=subject or os.path.basename(pdf_path),
            sender=sender,
            signal=f'ocr: low_confidence: {e}',
            body_preview=pdf_path,
        )
        return None
    except VisionAPIError as e:
        logger.error(
            'OCR vision API failed | message_id=%s file=%s error=%s',
            message_id,
            pdf_path,
            e,
        )
        _queue_ocr_issue(
            message_id=message_id or 'unknown',
            subject=subject or os.path.basename(pdf_path),
            sender=sender,
            signal=f'ocr: vision_api_error: {e}',
            body_preview=pdf_path,
        )
        return None
    except Exception as e:
        logger.exception(
            'OCR unexpected failure | message_id=%s file=%s',
            message_id,
            pdf_path,
        )
        _queue_ocr_issue(
            message_id=message_id or 'unknown',
            subject=subject or os.path.basename(pdf_path),
            sender=sender,
            signal=f'ocr: unexpected_error: {e}',
            body_preview=pdf_path,
        )
        return None

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    payload = result.model_dump(mode='json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    logger.info(
        'OCR complete | message_id=%s file=%s out=%s confidence=%.3f warnings=%s model=%s',
        message_id,
        pdf_path,
        out_path,
        result.overall_confidence,
        len(result.warnings),
        result.model_used,
    )
    return out_path
