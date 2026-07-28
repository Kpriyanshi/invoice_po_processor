from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Invoice, InvoiceLineItem


def upsert_ocr_result(
    session: Session,
    result,
    *,
    message_id: str = "",
    subject: str = "",
    sender: str = "",
) -> uuid.UUID:
    """
    Insert or update an invoice row from OCRExtractionResult.
    Unique key: source_file.
    """
    data = result.data
    source_file = result.source_file
    payload = result.model_dump(mode="json")

    existing = session.scalar(select(Invoice).where(Invoice.source_file == source_file))
    if existing is None:
        invoice = Invoice(id=uuid.uuid4(), source_file=source_file)
        session.add(invoice)
    else:
        invoice = existing
        invoice.line_items.clear()

    invoice.message_id = message_id or None
    invoice.subject = subject or None
    invoice.sender = sender or None
    invoice.document_type = getattr(data.document_type, "value", data.document_type)
    invoice.document_label = data.document_label
    invoice.invoice_number = data.invoice_number
    invoice.invoice_date = data.invoice_date
    invoice.po_number = data.po_number
    invoice.vendor_name = data.vendor_name
    invoice.vendor_gstin = data.vendor_gstin
    invoice.buyer_name = data.buyer_name
    invoice.buyer_gstin = data.buyer_gstin
    invoice.currency = data.currency
    invoice.subtotal = data.subtotal
    invoice.tax_amount = data.tax_amount
    invoice.cgst_amount = data.cgst_amount
    invoice.sgst_amount = data.sgst_amount
    invoice.igst_amount = data.igst_amount
    invoice.total_amount = data.total_amount
    invoice.overall_confidence = result.overall_confidence
    invoice.model_used = result.model_used
    invoice.raw_extraction = payload

    for i, item in enumerate(data.line_items or [], start=1):
        invoice.line_items.append(
            InvoiceLineItem(
                id=uuid.uuid4(),
                line_no=i,
                description=item.description or item.product_name or "",
                quantity=item.quantity,
                unit=item.unit,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
        )

    session.flush()
    return invoice.id