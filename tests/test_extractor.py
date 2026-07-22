from app.services.ocr.extractor import (
    extract_invoice_fields,
    extract_line_items,
    extracted_fields_to_json,
)

NIGAM_RAW = """BILL OF SUPPLY
GSTIN: O9BQLPK8114P1Z4
Invoice
SL/24-25/57
Invoice Date: 08/05/2026
ITEMS
QTY:
RATE
AMOUNT
DELL LAPTOP REPAIR
PCS
2,200
2,200
latitude 5490 ssd problem
UPS REPAIR
PCS
1,500
1,500
UPS CARD REPAIR AND BAT
SUBTOTAL
3,700
Total Amount
{3,700
"""


def test_nigam_header_fields():
    fields = extract_invoice_fields(NIGAM_RAW, line_confs=[0.9] * 20)
    j = extracted_fields_to_json(fields)
    assert j["gstin"]["value"] == "09BQLPK8114P1Z4"
    assert j["invoice_no"]["value"] == "SL/24-25/57"
    assert j["invoice_date"]["value"] == "08/05/2026"
    assert j["subtotal"]["value"] == "3,700"
    assert j["total_amount"]["value"] == "3,700"
    assert j["grand_total"]["value"] == "3,700"


def test_nigam_line_items():
    items = extract_line_items(NIGAM_RAW, avg_ocr_conf=0.9)
    assert len(items) >= 2
    assert "DELL LAPTOP REPAIR" in items[0]["description"]
    assert items[0]["unit_price"] == "2,200"
    assert items[0]["line_total"] == "2,200"
    assert "UPS REPAIR" in items[1]["description"]


def test_alias_labels_igst_and_bill_no():
    text = """
    GST No: 27AAPFU0939F1ZV
    Bill No: INV-1001
    Dated: 01/02/2025
    DESCRIPTION
    Widget A
    NOS
    2
    100.00
    200.00
    Taxable Value
    200.00
    IGST
    36.00
    Grand Total
    236.00
    """
    j = extracted_fields_to_json(extract_invoice_fields(text, [0.9] * 10))
    assert j["gstin"]["value"] == "27AAPFU0939F1ZV"
    assert j["invoice_no"]["value"] == "INV-1001"
    assert j["invoice_date"]["value"] == "01/02/2025"
    assert j["subtotal"]["value"] == "200.00"
    assert j["igst"]["value"] == "36.00"
    assert j["tax_total"]["value"] == "36.00"
    assert j["grand_total"]["value"] == "236.00"

    items = extract_line_items(text, avg_ocr_conf=0.9)
    assert len(items) == 1
    assert items[0]["description"] == "Widget A"
    assert items[0]["quantity"] == "2"
    assert items[0]["unit"] == "NOS"
    assert items[0]["unit_price"] == "100.00"
    assert items[0]["line_total"] == "200.00"
