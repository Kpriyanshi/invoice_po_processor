"""Exception case taxonomy: category + root-cause tags for the review queue."""

from __future__ import annotations

from enum import StrEnum


class ExceptionCategory(StrEnum):
    CLASSIFICATION = "classification"
    SECURITY = "security"
    OCR = "ocr"
    GSTIN = "gstin"
    PERSISTENCE = "persistence"
    OTHER = "other"


class ExceptionRootCause(StrEnum):
    CLASSIFICATION_LOW_CONFIDENCE = "CLASSIFICATION_LOW_CONFIDENCE"
    SECURITY_ALL_ATTACHMENTS_REJECTED = "SECURITY_ALL_ATTACHMENTS_REJECTED"
    OCR_LOW_CONFIDENCE = "OCR_LOW_CONFIDENCE"
    OCR_VISION_API_ERROR = "OCR_VISION_API_ERROR"
    OCR_MODULE_IMPORT_FAILED = "OCR_MODULE_IMPORT_FAILED"
    OCR_UNEXPECTED_ERROR = "OCR_UNEXPECTED_ERROR"
    OCR_DB_UPSERT_FAILED = "OCR_DB_UPSERT_FAILED"
    GSTIN_VENDOR_MISSING = "GSTIN_VENDOR_MISSING"
    GSTIN_VENDOR_INVALID = "GSTIN_VENDOR_INVALID"
    GSTIN_BUYER_INVALID = "GSTIN_BUYER_INVALID"
    GSTIN_VALIDATION_FAILED = "GSTIN_VALIDATION_FAILED"
    UNKNOWN = "UNKNOWN"


def infer_exception_tags(
    signals: list[str] | None = None,
    reason: str = "",
) -> tuple[str, str]:
    """
    Infer (category, root_cause) from signals/reason text.
    Returns string values suitable for JSON persistence.
    """
    blob = " ".join(signals or []).lower()
    if reason:
        blob = f"{blob} {reason.lower()}"

    # Security
    if "security: all attachments rejected" in blob or "all attachments rejected" in blob:
        return (
            ExceptionCategory.SECURITY.value,
            ExceptionRootCause.SECURITY_ALL_ATTACHMENTS_REJECTED.value,
        )

    # GSTIN (more specific first)
    if "vendor_gstin missing" in blob or "vendor_gstin missing" in blob.replace("_", " "):
        return (
            ExceptionCategory.GSTIN.value,
            ExceptionRootCause.GSTIN_VENDOR_MISSING.value,
        )
    if "vendor_gstin invalid" in blob or "vendor_gstin invalid" in blob:
        return (
            ExceptionCategory.GSTIN.value,
            ExceptionRootCause.GSTIN_VENDOR_INVALID.value,
        )
    if "buyer_gstin invalid" in blob:
        return (
            ExceptionCategory.GSTIN.value,
            ExceptionRootCause.GSTIN_BUYER_INVALID.value,
        )
    if "gstin" in blob:
        return (
            ExceptionCategory.GSTIN.value,
            ExceptionRootCause.GSTIN_VALIDATION_FAILED.value,
        )

    # OCR / persistence
    if "db_upsert_failed" in blob or "ocr: db_upsert_failed" in blob:
        return (
            ExceptionCategory.PERSISTENCE.value,
            ExceptionRootCause.OCR_DB_UPSERT_FAILED.value,
        )
    if "module_import_failed" in blob:
        return (
            ExceptionCategory.OCR.value,
            ExceptionRootCause.OCR_MODULE_IMPORT_FAILED.value,
        )
    if "vision_api_error" in blob:
        return (
            ExceptionCategory.OCR.value,
            ExceptionRootCause.OCR_VISION_API_ERROR.value,
        )
    if "low_confidence" in blob and "ocr:" in blob:
        return (
            ExceptionCategory.OCR.value,
            ExceptionRootCause.OCR_LOW_CONFIDENCE.value,
        )
    if "unexpected_error" in blob and "ocr:" in blob:
        return (
            ExceptionCategory.OCR.value,
            ExceptionRootCause.OCR_UNEXPECTED_ERROR.value,
        )
    if blob.strip().startswith("ocr:") or " ocr:" in f" {blob}":
        return (
            ExceptionCategory.OCR.value,
            ExceptionRootCause.OCR_UNEXPECTED_ERROR.value,
        )

    # Classification (keyword signals from classifier, no ocr/security/gstin prefix)
    if any(
        s.startswith("subject:") or s.startswith("body:") or s.startswith("attachment")
        for s in (signals or [])
    ):
        return (
            ExceptionCategory.CLASSIFICATION.value,
            ExceptionRootCause.CLASSIFICATION_LOW_CONFIDENCE.value,
        )

    return ExceptionCategory.OTHER.value, ExceptionRootCause.UNKNOWN.value


def root_cause_from_gstin_failures(failures: list) -> str:
    """Pick the most specific GSTIN root cause from GstinApiCheckResult list."""
    parties = {getattr(f, "party", "") for f in failures}
    reasons = " ".join(getattr(f, "reason", "") for f in failures).lower()

    if any(getattr(f, "party", "") == "vendor" and "missing" in getattr(f, "reason", "").lower() for f in failures):
        return ExceptionRootCause.GSTIN_VENDOR_MISSING.value
    if any(getattr(f, "party", "") == "vendor" for f in failures) and "invalid" in reasons:
        return ExceptionRootCause.GSTIN_VENDOR_INVALID.value
    if "buyer" in parties and "invalid" in reasons:
        return ExceptionRootCause.GSTIN_BUYER_INVALID.value
    return ExceptionRootCause.GSTIN_VALIDATION_FAILED.value
