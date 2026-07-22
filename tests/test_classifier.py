import base64

from app.services.classifier import (
    classify_email,
    get_attachments,
    score_attachments,
    score_subject,
)


def test_score_subject_invoice():
    score, signals = score_subject('Tax Invoice #12345')
    assert score > 0
    assert any('invoice' in s for s in signals)


def test_classify_email_high_confidence():
    message = {
        'payload': {
            'headers': [
                {'name': 'Subject', 'value': 'Tax Invoice #INV-001'},
                {'name': 'From', 'value': 'vendor@example.com'},
            ],
            'parts': [
                {
                    'mimeType': 'text/plain',
                    'body': {
                        'data': 'aW52b2ljZSBubyBJTlYtMDAxIGFtb3VudCBkdWUgZ3N0aW4=',
                    },
                },
                {'filename': 'invoice.pdf', 'body': {}},
            ],
        },
    }
    result = classify_email(message)
    assert result['verdict'] == 'store'
    assert result['confidence'] >= 85


def test_classify_email_skip():
    message = {
        'payload': {
            'headers': [
                {'name': 'Subject', 'value': 'Hello there'},
                {'name': 'From', 'value': 'friend@example.com'},
            ],
            'body': {'data': 'SGVsbG8h'},
        },
    }
    result = classify_email(message)
    assert result['verdict'] == 'skip'
    assert result['confidence'] < 40


def test_invoice_submission_with_pdf_stores():
    body = base64.urlsafe_b64encode(
        b'Please find the attached tax invoice for processing.'
    ).decode()
    message = {
        'payload': {
            'headers': [
                {'name': 'Subject', 'value': 'Invoice Submission'},
                {'name': 'From', 'value': 'vendor@example.com'},
            ],
            'parts': [
                {'mimeType': 'text/plain', 'body': {'data': body}},
                {
                    'filename': 'NIGAM_SAINI_Invoice.pdf',
                    'body': {'attachmentId': 'x'},
                },
            ],
        },
    }
    result = classify_email(message)
    assert result['verdict'] == 'store'
    assert result['confidence'] >= 60


def test_pdf_only_does_not_store():
    message = {
        'payload': {
            'headers': [
                {'name': 'Subject', 'value': 'Hello'},
                {'name': 'From', 'value': 'x@y.com'},
            ],
            'parts': [
                {
                    'mimeType': 'text/plain',
                    'body': {'data': base64.urlsafe_b64encode(b'hi').decode()},
                },
                {'filename': 'scan.pdf', 'body': {'attachmentId': 'x'}},
            ],
        },
    }
    result = classify_email(message)
    assert result['verdict'] != 'store'
    assert result['confidence'] < 60


def test_nested_mime_finds_attachment():
    payload = {
        'parts': [
            {
                'mimeType': 'multipart/mixed',
                'parts': [
                    {'mimeType': 'text/plain', 'body': {'data': ''}},
                    {'filename': 'bill.pdf', 'body': {'attachmentId': '1'}},
                ],
            }
        ],
    }
    assert get_attachments(payload) == ['bill.pdf']


def test_filename_invoice_bonus():
    score, signals = score_attachments(['NIGAM_SAINI_Invoice.pdf'])
    assert score >= 25
    assert any('attachment-name' in s for s in signals)
