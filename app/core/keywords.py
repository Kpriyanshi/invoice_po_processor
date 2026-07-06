SUBJECT_KEYWORDS = {
    'invoice': 40,
    'tax invoice': 45,
    'gst invoice': 45,
    'proforma invoice': 40,
    'purchase order': 40,
    'po#': 35,
    'credit note': 30,
    'bill': 15,
    'payment due': 30,
    'overdue': 25,
    'receipt': 10,
    'statement': 10,
}

BODY_KEYWORDS = {
    'invoice no': 20,
    'invoice number': 20,
    'invoice #': 20,
    'amount due': 20,
    'total amount': 15,
    'due date': 15,
    'payment terms': 15,
    'gstin': 20,
    'gst': 10,
    'bank account': 10,
    'purchase order': 20,
    'po number': 20,
    'grand total': 15,
    'subtotal': 10,
    'net 30': 15,
    'net 60': 15,
    'please pay': 15,
    'payment due': 15,
    'overdue': 15,
}

INVOICE_ATTACHMENT_TYPES = {
    '.pdf': 25,
    '.docx': 15,
    '.xlsx': 10,
    '.doc': 10,
}

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
]
