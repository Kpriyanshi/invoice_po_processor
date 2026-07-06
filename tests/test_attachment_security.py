import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.services.attachment import save_attachments

MINIMAL_PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF'
EXE_BYTES = b'MZ\x90\x00' + b'\x00' * 64


@pytest.fixture
def gmail_payload():
    return {
        'parts': [
            {
                'filename': 'invoice.pdf',
                'body': {'attachmentId': 'att-1'},
            },
            {
                'filename': 'evil.pdf',
                'body': {'attachmentId': 'att-2'},
            },
        ],
    }


def test_rejects_malicious_attachment_before_save(tmp_path, gmail_payload, monkeypatch):
    monkeypatch.setenv('INVOICE_SAVE_FOLDER', str(tmp_path))
    monkeypatch.setenv('QUARANTINE_PATH', str(tmp_path / 'quarantine.json'))
    monkeypatch.setenv('MALWARE_SCAN_ENABLED', 'false')
    from app.core.config import get_settings

    get_settings.cache_clear()

    mock_service = MagicMock()

    def fake_get_attachment(userId, messageId, id):
        data = MINIMAL_PDF if id == 'att-1' else EXE_BYTES
        import base64

        return MagicMock(execute=MagicMock(return_value={'data': base64.urlsafe_b64encode(data).decode()}))

    mock_service.users.return_value.messages.return_value.attachments.return_value.get = fake_get_attachment

    with patch('app.services.attachment.get_gmail_service', return_value=mock_service):
        result = save_attachments('msg-1', gmail_payload, 'Test Invoice', sender='v@test.com')

    assert result.attempted_count == 2
    assert result.rejected_count == 1
    assert len(result.saved_paths) == 1
    assert not any('evil' in p for p in result.saved_paths)

    quarantine = json.loads((tmp_path / 'quarantine.json').read_text())
    assert len(quarantine) == 1
    assert quarantine[0]['filename'] == 'evil.pdf'

    get_settings.cache_clear()
