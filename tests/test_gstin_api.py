from unittest.mock import MagicMock, patch

from app.services.validation.gstin_api import (
    GstinApiCheckResult,
    validate_party_gstins,
    verify_gstin_via_api,
)


def test_verify_gstin_local_invalid(monkeypatch):
    monkeypatch.setenv('GSTIN_API_KEY', 'test-key')
    from app.core.config import get_settings

    get_settings.cache_clear()
    result = verify_gstin_via_api('NOT-A-GSTIN')
    assert result.ok is False
    assert 'local format invalid' in result.reason
    get_settings.cache_clear()


def test_verify_gstin_api_flag_false(monkeypatch):
    monkeypatch.setenv('GSTIN_API_KEY', 'test-key')
    monkeypatch.setenv('GSTIN_API_BASE_URL', 'https://sheet.gstincheck.co.in')
    from app.core.config import get_settings

    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'flag': False,
        'message': 'Invalid GSTIN',
        'errorCode': 'INVALID',
        'data': {},
    }

    with patch('app.services.validation.gstin_api.validate_gstin') as mock_local:
        mock_local.return_value = MagicMock(
            is_valid=True, normalized='09BQLPK8114P1Z4', reason='valid'
        )
        with patch('httpx.Client') as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__.return_value = mock_client
            mock_client.__exit__.return_value = False
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client
            result = verify_gstin_via_api('09BQLPK8114P1Z4')

    assert result.ok is False
    assert 'gstin API rejected' in result.reason
    get_settings.cache_clear()


def test_verify_gstin_api_success(monkeypatch):
    monkeypatch.setenv('GSTIN_API_KEY', 'test-key')
    from app.core.config import get_settings

    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'flag': True,
        'message': 'Success',
        'data': {'gstin_status': 'Active', 'legal_name': 'Test Co'},
    }

    with patch('app.services.validation.gstin_api.validate_gstin') as mock_local:
        mock_local.return_value = MagicMock(
            is_valid=True, normalized='09BQLPK8114P1Z4', reason='valid'
        )
        with patch('httpx.Client') as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__.return_value = mock_client
            mock_client.__exit__.return_value = False
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client
            result = verify_gstin_via_api('09BQLPK8114P1Z4')

    assert result.ok is True
    get_settings.cache_clear()


def test_validate_party_gstins_queues_vendor_missing(monkeypatch):
    monkeypatch.setenv('GSTIN_API_VALIDATION_ENABLED', 'true')
    monkeypatch.setenv('GSTIN_API_KEY', 'test-key')
    from app.core.config import get_settings

    get_settings.cache_clear()
    failures = validate_party_gstins(None, None)
    assert len(failures) == 1
    assert failures[0].party == 'vendor'
    assert 'missing' in failures[0].reason
    get_settings.cache_clear()


def test_validate_party_gstins_buyer_invalid(monkeypatch):
    monkeypatch.setenv('GSTIN_API_VALIDATION_ENABLED', 'true')
    monkeypatch.setenv('GSTIN_API_KEY', 'test-key')
    from app.core.config import get_settings

    get_settings.cache_clear()

    def fake_verify(gstin: str) -> GstinApiCheckResult:
        if gstin.startswith('09'):
            return GstinApiCheckResult(party='', gstin=gstin, ok=True, reason='ok')
        return GstinApiCheckResult(
            party='', gstin=gstin, ok=False, reason='gstin API rejected: Invalid'
        )

    with patch(
        'app.services.validation.gstin_api.verify_gstin_via_api',
        side_effect=fake_verify,
    ):
        failures = validate_party_gstins('09BQLPK8114P1Z4', '27AAAAA0000A1Z5')

    assert len(failures) == 1
    assert failures[0].party == 'buyer'
    assert 'buyer_gstin invalid' in failures[0].reason
    get_settings.cache_clear()


def test_validate_party_gstins_disabled(monkeypatch):
    monkeypatch.setenv('GSTIN_API_VALIDATION_ENABLED', 'false')
    monkeypatch.setenv('GSTIN_API_KEY', 'test-key')
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert validate_party_gstins(None, None) == []
    get_settings.cache_clear()
