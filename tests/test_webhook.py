import base64
import json
from unittest.mock import patch

from app.services.processor import process_gmail_notification


def test_health(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'running'}


def test_queue(client):
    response = client.get('/queue')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_webhook_empty_body(client):
    response = client.post('/webhook', json=None)
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_webhook_processes_notification(client):
    history_id = '888888'
    notification = json.dumps({'historyId': history_id})
    encoded = base64.b64encode(notification.encode()).decode()
    payload = {'message': {'data': encoded}}

    with patch('app.api.v1.webhook.process_gmail_notification') as mock_process:
        response = client.post('/webhook', json=payload)
        assert response.status_code == 200
        mock_process.assert_called_once_with(history_id)


def test_duplicate_history_id_skipped():
    with patch('app.services.processor.load_processed_ids', return_value={'999999'}):
        with patch('app.services.processor.save_processed_id') as mock_save:
            with patch('app.services.processor.get_gmail_service'):
                process_gmail_notification('999999')
                mock_save.assert_not_called()


def test_webhook_always_returns_ok_on_error(client):
    payload = {'message': {'data': 'not-valid-base64-json!!!'}}

    response = client.post('/webhook', json=payload)
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
