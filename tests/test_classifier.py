from app.services.classifier import classify_email, score_subject


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
