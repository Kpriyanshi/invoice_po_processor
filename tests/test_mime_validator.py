import pytest

from app.core.config import Settings, get_settings
from app.services.security.mime_validator import validate_attachment

MINIMAL_PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF'
EXE_BYTES = b'MZ\x90\x00' + b'\x00' * 64


@pytest.fixture(autouse=True)
def enable_mime_validation(monkeypatch):
    monkeypatch.setenv('MIME_VALIDATION_ENABLED', 'true')
    monkeypatch.setenv('MAX_ATTACHMENT_SIZE_MB', '25')
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_valid_pdf_passes():
    result = validate_attachment('invoice.pdf', MINIMAL_PDF)
    assert result.valid is True
    assert result.detected_mime == 'application/pdf'


def test_exe_with_pdf_extension_fails():
    result = validate_attachment('invoice.pdf', EXE_BYTES)
    assert result.valid is False
    assert 'mismatch' in (result.reason or '') or 'not_allowed' in (result.reason or '')


def test_empty_file_fails():
    result = validate_attachment('invoice.pdf', b'')
    assert result.valid is False
    assert result.reason == 'empty_file'


def test_disallowed_extension_fails():
    result = validate_attachment('malware.exe', EXE_BYTES)
    assert result.valid is False
    assert 'disallowed_extension' in (result.reason or '')


def test_file_too_large_fails(monkeypatch):
    monkeypatch.setenv('MAX_ATTACHMENT_SIZE_MB', '0')
    get_settings.cache_clear()
    result = validate_attachment('invoice.pdf', MINIMAL_PDF)
    assert result.valid is False
    assert 'file_too_large' in (result.reason or '')


def test_validation_disabled(monkeypatch):
    monkeypatch.setenv('MIME_VALIDATION_ENABLED', 'false')
    get_settings.cache_clear()
    result = validate_attachment('malware.exe', EXE_BYTES)
    assert result.valid is True
    assert result.reason == 'validation_disabled'
