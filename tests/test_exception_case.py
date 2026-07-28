import json

from app.services.exception_case import (
    ExceptionCategory,
    ExceptionRootCause,
    infer_exception_tags,
    root_cause_from_gstin_failures,
)
from app.services.exception_queue import add_to_queue, load_queue, mark_reviewed
from app.services.validation.gstin_api import GstinApiCheckResult


def test_infer_security():
    cat, root = infer_exception_tags(
        ['subject: invoice', 'security: all attachments rejected']
    )
    assert cat == ExceptionCategory.SECURITY.value
    assert root == ExceptionRootCause.SECURITY_ALL_ATTACHMENTS_REJECTED.value


def test_infer_gstin_vendor_invalid():
    cat, root = infer_exception_tags(
        ['gstin: vendor_gstin invalid: gstin API rejected: Invalid']
    )
    assert cat == ExceptionCategory.GSTIN.value
    assert root == ExceptionRootCause.GSTIN_VENDOR_INVALID.value


def test_infer_ocr_vision():
    cat, root = infer_exception_tags(['ocr: vision_api_error: rate limit'])
    assert cat == ExceptionCategory.OCR.value
    assert root == ExceptionRootCause.OCR_VISION_API_ERROR.value


def test_infer_classification():
    cat, root = infer_exception_tags(
        ["subject: 'invoice'", "body: 'gst'"],
        reason='confidence below threshold',
    )
    assert cat == ExceptionCategory.CLASSIFICATION.value
    assert root == ExceptionRootCause.CLASSIFICATION_LOW_CONFIDENCE.value


def test_infer_db_upsert():
    cat, root = infer_exception_tags(['ocr: db_upsert_failed: boom'])
    assert cat == ExceptionCategory.PERSISTENCE.value
    assert root == ExceptionRootCause.OCR_DB_UPSERT_FAILED.value


def test_root_cause_from_gstin_failures_vendor_missing():
    failures = [
        GstinApiCheckResult(
            party='vendor',
            gstin=None,
            ok=False,
            reason='vendor_gstin missing — rejected for manual review',
        )
    ]
    assert (
        root_cause_from_gstin_failures(failures)
        == ExceptionRootCause.GSTIN_VENDOR_MISSING.value
    )


def test_add_to_queue_writes_case_fields(tmp_path, monkeypatch):
    queue_path = tmp_path / 'exception_queue.json'
    monkeypatch.setenv('EXCEPTION_QUEUE_PATH', str(queue_path))
    from app.core.config import get_settings

    get_settings.cache_clear()

    case_id = add_to_queue(
        'msg-abc',
        {
            'subject': 'Tax Invoice',
            'sender': 'a@b.com',
            'confidence': 55,
            'signals': ["subject: 'invoice'"],
            'body_preview': 'preview',
            'category': ExceptionCategory.CLASSIFICATION.value,
            'root_cause': ExceptionRootCause.CLASSIFICATION_LOW_CONFIDENCE.value,
            'reason': 'low confidence',
        },
    )

    assert case_id
    data = json.loads(queue_path.read_text(encoding='utf-8'))
    assert len(data) == 1
    case = data[0]
    assert case['case_id'] == case_id
    assert case['timestamp']
    assert case['category'] == 'classification'
    assert case['root_cause'] == 'CLASSIFICATION_LOW_CONFIDENCE'
    assert case['status'] == 'pending_review'
    get_settings.cache_clear()


def test_add_to_queue_infers_tags_when_missing(tmp_path, monkeypatch):
    queue_path = tmp_path / 'exception_queue.json'
    monkeypatch.setenv('EXCEPTION_QUEUE_PATH', str(queue_path))
    from app.core.config import get_settings

    get_settings.cache_clear()

    add_to_queue(
        'msg-1',
        {
            'subject': 'Invoice',
            'sender': 'a@b.com',
            'confidence': 90,
            'signals': ['security: all attachments rejected'],
            'body_preview': '',
        },
    )
    case = load_queue()[0]
    assert case['category'] == 'security'
    assert case['root_cause'] == 'SECURITY_ALL_ATTACHMENTS_REJECTED'
    get_settings.cache_clear()


def test_mark_reviewed_by_case_id(tmp_path, monkeypatch):
    queue_path = tmp_path / 'exception_queue.json'
    monkeypatch.setenv('EXCEPTION_QUEUE_PATH', str(queue_path))
    from app.core.config import get_settings

    get_settings.cache_clear()

    case_id = add_to_queue(
        'msg-dup',
        {
            'subject': 'A',
            'sender': 'a@b.com',
            'confidence': 40,
            'signals': ["body: 'invoice'"],
            'body_preview': '',
            'category': 'classification',
            'root_cause': 'CLASSIFICATION_LOW_CONFIDENCE',
        },
    )
    other_id = add_to_queue(
        'msg-dup',
        {
            'subject': 'B',
            'sender': 'a@b.com',
            'confidence': 40,
            'signals': ["body: 'invoice'"],
            'body_preview': '',
            'category': 'classification',
            'root_cause': 'CLASSIFICATION_LOW_CONFIDENCE',
        },
    )

    assert mark_reviewed(case_id, approved=True) is True
    queue = load_queue()
    by_id = {c['case_id']: c for c in queue}
    assert by_id[case_id]['status'] == 'approved'
    assert by_id[case_id]['reviewed_at']
    assert by_id[other_id]['status'] == 'pending_review'
    assert mark_reviewed('missing-case', approved=False) is False
    get_settings.cache_clear()
