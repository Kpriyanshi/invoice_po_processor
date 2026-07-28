from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.services.exception_case import (
    ExceptionCategory,
    ExceptionRootCause,
    root_cause_from_gstin_failures,
)
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
    signals: list[str] | None = None,
    reason: str = '',
    category: str = '',
    root_cause: str = '',
) -> None:
    signal_list = list(signals) if signals else [signal]
    payload = {
        'subject': subject,
        'sender': sender,
        'confidence': confidence,
        'signals': signal_list,
        'reason': reason or '; '.join(signal_list),
        'body_preview': body_preview,
    }
    if category:
        payload['category'] = category
    if root_cause:
        payload['root_cause'] = root_cause
    add_to_queue(message_id, payload)


def _validate_gstins_after_ocr(
    result,
    *,
    message_id: str,
    subject: str,
    sender: str,
    pdf_path: str,
) -> None:
    """
    Live GSTIN check for vendor (required) and buyer (if present).
    On failure, queue for manual review with an explicit rejection reason.
    JSON/Postgres already saved — queue does not undo extraction.
    """
    from app.services.validation.gstin_api import validate_party_gstins

    data = getattr(result, 'data', None)
    vendor_gstin = getattr(data, 'vendor_gstin', None) if data is not None else None
    buyer_gstin = getattr(data, 'buyer_gstin', None) if data is not None else None

    failures = validate_party_gstins(vendor_gstin, buyer_gstin)
    if not failures:
        return

    signals = [f'gstin: {f.reason}' for f in failures]
    reason = (
        'Rejected for further processing — GSTIN validation failed. '
        + '; '.join(signals)
    )
    logger.warning(
        'GSTIN validation failed | message_id=%s file=%s reasons=%s',
        message_id,
        pdf_path,
        signals,
    )
    _queue_ocr_issue(
        message_id=message_id or 'unknown',
        subject=subject or os.path.basename(pdf_path),
        sender=sender,
        signal=signals[0],
        signals=signals,
        reason=reason,
        body_preview=pdf_path,
        confidence=int(round(float(getattr(result, 'overall_confidence', 0) or 0) * 100)),
        category=ExceptionCategory.GSTIN.value,
        root_cause=root_cause_from_gstin_failures(failures),
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
            category=ExceptionCategory.OCR.value,
            root_cause=ExceptionRootCause.OCR_MODULE_IMPORT_FAILED.value,
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
            category=ExceptionCategory.OCR.value,
            root_cause=ExceptionRootCause.OCR_LOW_CONFIDENCE.value,
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
            category=ExceptionCategory.OCR.value,
            root_cause=ExceptionRootCause.OCR_VISION_API_ERROR.value,
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
            category=ExceptionCategory.OCR.value,
            root_cause=ExceptionRootCause.OCR_UNEXPECTED_ERROR.value,
        )
        return None

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    payload = result.model_dump(mode='json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # Dual-write to Postgres (JSON already saved; DB failure must not undo OCR)
    if settings.database_url:
        try:
            from app.db.repository import upsert_ocr_result
            from app.db.session import SessionLocal

            if SessionLocal is None:
                raise RuntimeError('DATABASE_URL set but SessionLocal is None')

            with SessionLocal() as session:
                invoice_id = upsert_ocr_result(
                    session,
                    result,
                    message_id=message_id,
                    subject=subject,
                    sender=sender,
                )
                session.commit()
            logger.info(
                'OCR DB upsert ok | message_id=%s invoice_id=%s source_file=%s',
                message_id,
                invoice_id,
                result.source_file,
            )
        except Exception as e:
            logger.exception(
                'OCR DB upsert failed | message_id=%s file=%s',
                message_id,
                pdf_path,
            )
            _queue_ocr_issue(
                message_id=message_id or 'unknown',
                subject=subject or os.path.basename(pdf_path),
                sender=sender,
                signal=f'ocr: db_upsert_failed: {e}',
                body_preview=pdf_path,
                category=ExceptionCategory.PERSISTENCE.value,
                root_cause=ExceptionRootCause.OCR_DB_UPSERT_FAILED.value,
            )

    _validate_gstins_after_ocr(
        result,
        message_id=message_id,
        subject=subject,
        sender=sender,
        pdf_path=pdf_path,
    )

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
