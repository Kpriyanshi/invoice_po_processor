import base64
import json
from unittest.mock import MagicMock, patch

from app.services.ocr.vision_service import OcrJob
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

    with patch('app.api.v1.webhook.process_gmail_notification', return_value=[]) as mock_process:
        response = client.post('/webhook', json=payload)
        assert response.status_code == 200
        mock_process.assert_called_once_with(history_id)


def test_webhook_schedules_ocr_background_tasks(client):
    history_id = '777777'
    notification = json.dumps({'historyId': history_id})
    encoded = base64.b64encode(notification.encode()).decode()
    payload = {'message': {'data': encoded}}

    jobs = [
        OcrJob(
            path=r'data\invoices\Invoice_a.pdf',
            message_id='msg-1',
            subject='Invoice Submission',
            sender='vendor@example.com',
        )
    ]

    with patch(
        'app.api.v1.webhook.process_gmail_notification',
        return_value=jobs,
    ):
        with patch('app.api.v1.webhook.run_vision_ocr_job') as mock_ocr:
            response = client.post('/webhook', json=payload)
            assert response.status_code == 200
            assert response.json() == {'status': 'ok'}
            mock_ocr.assert_called_once_with(
                jobs[0].path,
                message_id='msg-1',
                subject='Invoice Submission',
                sender='vendor@example.com',
            )


def test_duplicate_history_id_skipped():
    with patch('app.services.processor.load_processed_ids', return_value={'999999'}):
        with patch('app.services.processor.save_processed_id') as mock_save:
            with patch('app.services.processor.get_gmail_service'):
                jobs = process_gmail_notification('999999')
                mock_save.assert_not_called()
                assert jobs == []


def test_processor_returns_ocr_jobs_for_saved_pdfs():
    message = {
        'payload': {'parts': []},
        'snippet': 'tax invoice attached',
    }
    classify_result = {
        'verdict': 'store',
        'confidence': 90,
        'signals': ['subject: invoice'],
        'subject': 'Invoice Submission',
        'sender': 'a@b.com',
        'body_preview': 'please find invoice',
        'attachments': [{'filename': 'inv.pdf'}],
    }
    save_result = MagicMock()
    save_result.attempted_count = 1
    save_result.rejected_count = 0
    save_result.saved_paths = [r'data\invoices\Invoice Submission_inv.pdf']

    with patch('app.services.processor.load_processed_ids', return_value=set()):
        with patch('app.services.processor.save_processed_id'):
            with patch('app.services.processor.save_last_history_id'):
                with patch('app.services.processor.get_last_history_id', return_value='1'):
                    service = MagicMock()
                    service.users().history().list().execute.return_value = {
                        'history': [
                            {
                                'messagesAdded': [
                                    {'message': {'id': 'msg-pdf'}}
                                ]
                            }
                        ]
                    }
                    service.users().messages().get().execute.return_value = message
                    with patch(
                        'app.services.processor.get_gmail_service',
                        return_value=service,
                    ):
                        with patch(
                            'app.services.processor.classify_email',
                            return_value=classify_result,
                        ):
                            with patch(
                                'app.services.processor.save_attachments',
                                return_value=save_result,
                            ):
                                jobs = process_gmail_notification('12345')

    assert len(jobs) == 1
    assert jobs[0].message_id == 'msg-pdf'
    assert jobs[0].path.endswith('inv.pdf')


def test_webhook_always_returns_ok_on_error(client):
    payload = {'message': {'data': 'not-valid-base64-json!!!'}}

    response = client.post('/webhook', json=payload)
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
