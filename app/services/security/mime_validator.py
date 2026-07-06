from dataclasses import dataclass

from app.core.config import get_settings

ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.xlsx', '.doc'}

# Office Open XML formats are ZIP-based; detectors may report application/zip
EXTENSION_TO_MIMES: dict[str, set[str]] = {
    '.pdf': {'application/pdf'},
    '.docx': {
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/zip',
    },
    '.xlsx': {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/zip',
    },
    '.doc': {'application/msword'},
}


@dataclass
class MimeValidationResult:
    valid: bool
    detected_mime: str | None = None
    reason: str | None = None


def _detect_mime(file_data: bytes) -> str | None:
    try:
        import magic

        return magic.from_buffer(file_data, mime=True)
    except (ImportError, OSError, AttributeError):
        pass

    import filetype

    kind = filetype.guess(file_data)
    return kind.mime if kind else None


def _get_allowed_extension(filename: str) -> str | None:
    lower = filename.lower()
    for ext in sorted(ALLOWED_EXTENSIONS, key=len, reverse=True):
        if lower.endswith(ext):
            return ext
    return None


def validate_attachment(filename: str, file_data: bytes) -> MimeValidationResult:
    settings = get_settings()

    if not settings.mime_validation_enabled:
        return MimeValidationResult(valid=True, detected_mime=None, reason='validation_disabled')

    if not file_data:
        return MimeValidationResult(valid=False, reason='empty_file')

    max_bytes = settings.max_attachment_size_mb * 1024 * 1024
    if len(file_data) > max_bytes:
        return MimeValidationResult(
            valid=False,
            reason=f'file_too_large: {len(file_data)} bytes exceeds {settings.max_attachment_size_mb}MB',
        )

    ext = _get_allowed_extension(filename)
    if ext is None:
        return MimeValidationResult(valid=False, reason=f'disallowed_extension: {filename}')

    detected_mime = _detect_mime(file_data)
    if not detected_mime:
        return MimeValidationResult(valid=False, reason='unknown_mime_type')

    allowed_mimes = settings.allowed_mime_set()
    if detected_mime not in allowed_mimes:
        return MimeValidationResult(
            valid=False,
            detected_mime=detected_mime,
            reason=f'mime_not_allowed: {detected_mime}',
        )

    expected_mimes = EXTENSION_TO_MIMES.get(ext, set())
    if detected_mime not in expected_mimes:
        return MimeValidationResult(
            valid=False,
            detected_mime=detected_mime,
            reason=f'extension_mime_mismatch: {ext} vs {detected_mime}',
        )

    return MimeValidationResult(valid=True, detected_mime=detected_mime)
