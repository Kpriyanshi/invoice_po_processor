import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ocr.vision_service import (
    extraction_output_path,
    is_ocr_supported,
    run_vision_ocr_job,
)


def test_is_ocr_supported():
    assert is_ocr_supported('a.pdf')
    assert is_ocr_supported('a.PNG')
    assert not is_ocr_supported('a.docx')
    assert not is_ocr_supported('a.xlsx')


def test_run_vision_ocr_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv('OCR_ENABLED', 'false')
    from app.core.config import get_settings

    get_settings.cache_clear()
    pdf = tmp_path / 'inv.pdf'
    pdf.write_bytes(b'%PDF-1.4')
    assert run_vision_ocr_job(str(pdf), message_id='m1') is None
    get_settings.cache_clear()


def test_run_vision_ocr_missing_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv('OCR_ENABLED', 'true')
    monkeypatch.setenv('OCR_OPENAI_API_KEY', '')
    monkeypatch.setenv('OCR_OUTPUT_DIR', str(tmp_path / 'extracted'))
    from app.core.config import get_settings

    get_settings.cache_clear()

    pdf = tmp_path / 'inv.pdf'
    pdf.write_bytes(b'%PDF-1.4')

    mock_settings = MagicMock()
    mock_settings.openai_api_key = ''

    with patch('ocr_module.OCRSettings', return_value=mock_settings):
        with patch('ocr_module.exceptions.LowConfidenceError', Exception):
            with patch('ocr_module.exceptions.VisionAPIError', Exception):
                with patch('ocr_module.GPT4VisionOCR') as mock_cls:
                    out = run_vision_ocr_job(
                        str(pdf),
                        message_id='m1',
                        subject='Invoice',
                        sender='a@b.com',
                    )
                    mock_cls.assert_not_called()

    assert out is None
    get_settings.cache_clear()


def test_run_vision_ocr_success_writes_json(tmp_path, monkeypatch):
    monkeypatch.setenv('OCR_ENABLED', 'true')
    monkeypatch.setenv('OCR_OPENAI_API_KEY', 'sk-test')
    monkeypatch.setenv('OCR_OUTPUT_DIR', str(tmp_path / 'extracted'))
    from app.core.config import get_settings

    get_settings.cache_clear()

    pdf = tmp_path / 'Invoice_test.pdf'
    pdf.write_bytes(b'%PDF-1.4')

    mock_result = MagicMock()
    mock_result.model_dump.return_value = {
        'source_file': str(pdf),
        'overall_confidence': 0.91,
        'warnings': [],
        'model_used': 'gpt-4o-2024-08-06',
        'data': {'invoice_number': 'INV-1'},
    }
    mock_result.overall_confidence = 0.91
    mock_result.warnings = []
    mock_result.model_used = 'gpt-4o-2024-08-06'

    mock_settings = MagicMock()
    mock_settings.openai_api_key = 'sk-test'

    with patch('ocr_module.OCRSettings', return_value=mock_settings):
        with patch('ocr_module.GPT4VisionOCR') as mock_cls:
            instance = mock_cls.return_value
            instance.extract = AsyncMock(return_value=mock_result)
            with patch('ocr_module.exceptions.LowConfidenceError', Exception):
                with patch('ocr_module.exceptions.VisionAPIError', Exception):
                    out = run_vision_ocr_job(
                        str(pdf),
                        message_id='msg-1',
                        subject='Invoice Submission',
                        sender='vendor@example.com',
                    )

    assert out is not None
    assert Path(out).is_file()
    data = json.loads(Path(out).read_text(encoding='utf-8'))
    assert data['overall_confidence'] == 0.91
    get_settings.cache_clear()


def test_run_vision_ocr_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv('OCR_ENABLED', 'true')
    monkeypatch.setenv('OCR_OPENAI_API_KEY', 'sk-test')
    monkeypatch.setenv('OCR_OUTPUT_DIR', str(tmp_path / 'extracted'))
    from app.core.config import get_settings

    get_settings.cache_clear()

    pdf = tmp_path / 'dup.pdf'
    pdf.write_bytes(b'%PDF-1.4')
    out = Path(extraction_output_path(str(pdf)))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('{"already": true}', encoding='utf-8')

    with patch('ocr_module.GPT4VisionOCR') as mock_cls:
        result = run_vision_ocr_job(str(pdf), message_id='m1')
        mock_cls.assert_not_called()

    assert result == str(out)
    get_settings.cache_clear()


def test_run_vision_ocr_api_error_queues(tmp_path, monkeypatch):
    monkeypatch.setenv('OCR_ENABLED', 'true')
    monkeypatch.setenv('OCR_OPENAI_API_KEY', 'sk-test')
    monkeypatch.setenv('OCR_OUTPUT_DIR', str(tmp_path / 'extracted'))
    from app.core.config import get_settings

    get_settings.cache_clear()

    pdf = tmp_path / 'bad.pdf'
    pdf.write_bytes(b'%PDF-1.4')

    class FakeOCRModuleError(Exception):
        pass

    class FakeLowConfidenceError(FakeOCRModuleError):
        pass

    class FakeVisionAPIError(FakeOCRModuleError):
        pass

    mock_settings = MagicMock()
    mock_settings.openai_api_key = 'sk-test'

    with patch('ocr_module.OCRSettings', return_value=mock_settings):
        with patch('ocr_module.GPT4VisionOCR') as mock_cls:
            instance = mock_cls.return_value
            instance.extract = AsyncMock(side_effect=FakeVisionAPIError('rate limit'))
            with patch('ocr_module.exceptions.LowConfidenceError', FakeLowConfidenceError):
                with patch('ocr_module.exceptions.VisionAPIError', FakeVisionAPIError):
                    with patch(
                        'app.services.ocr.vision_service.add_to_queue'
                    ) as mock_queue:
                        out = run_vision_ocr_job(
                            str(pdf),
                            message_id='msg-err',
                            subject='Invoice',
                            sender='a@b.com',
                        )

    assert out is None
    mock_queue.assert_called_once()
    args = mock_queue.call_args[0]
    assert args[0] == 'msg-err'
    assert 'ocr: vision_api_error' in args[1]['signals'][0]
    get_settings.cache_clear()
