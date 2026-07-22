"""
Structured output schemas for the GPT-4 Vision OCR module.

These models define exactly what fields the vision model is asked to
extract. They are deliberately shaped to match the "structured invoice
object" that Phase 3 (Validation & Compliance) and Phase 4 (PO Matching)
of the pipeline already expect, so this module can be dropped in as a
replacement for the EasyOCR/Tesseract + Pydantic-mapping step in Phase 2
with no downstream changes.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    INVOICE = "invoice"
    PURCHASE_ORDER = "purchase_order"
    GRN = "grn"
    UNKNOWN = "unknown"


class LineItem(BaseModel):
    """A single line item row from the document."""

    description: str = Field(
        description="Item/product name as printed in the line-items table (required for every row)"
    )
    product_name: Optional[str] = Field(
        default=None,
        description="Same as description when there is no separate product column; never leave null if description is set",
    )
    hsn_or_sac_code: Optional[str] = Field(
        default=None, description="HSN/SAC code if present"
    )
    quantity: Optional[float] = Field(default=None)
    unit: Optional[str] = Field(default=None, description="e.g. 'pcs', 'kg', 'hrs'")
    unit_price: Optional[float] = Field(
        default=None,
        description="Per-unit rate/price before tax (Rate, Unit Price, MRP column if that is the billable rate)",
    )
    list_price: Optional[float] = Field(
        default=None, description="List or MRP price per unit if shown separately"
    )
    tax_rate_percent: Optional[float] = Field(
        default=None,
        description="Overall GST rate on the line if shown (e.g. 18). Prefer specific CGST/SGST/IGST fields when printed.",
    )
    cgst_percent: Optional[float] = Field(
        default=None, description="CGST rate on this line, e.g. 9.0 for 9%"
    )
    sgst_percent: Optional[float] = Field(
        default=None, description="SGST/UTGST rate on this line, e.g. 9.0 for 9%"
    )
    igst_percent: Optional[float] = Field(
        default=None,
        description="IGST rate on this line as a number, e.g. 18.0 for 18% (not 0.18)",
    )
    line_total: Optional[float] = Field(
        default=None,
        description="Line amount before tax (taxable value for the row), not the invoice grand total",
    )


class InvoiceExtraction(BaseModel):
    """
    The structured object the vision model must return.

    Every field is Optional except the ones the model can always infer
    (document_type). A missing/unreadable field should be returned as
    null rather than guessed -- the model is explicitly instructed to do
    this in the system prompt (see vision_ocr.py).
    """

    document_type: DocumentType
    document_label: Optional[str] = Field(
        default=None,
        description="Exact printed document heading, e.g. 'Tax Invoice' or 'Purchase Order'",
    )

    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    order_date: Optional[date] = None
    due_date: Optional[date] = None

    po_number: Optional[str] = Field(
        default=None, description="Referenced PO number, for Phase 4 matching"
    )

    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = Field(
        default=None,
        description="Seller/supplier 15-character GSTIN (GSTIN/UIN of supplier); not the buyer GSTIN",
    )
    vendor_address: Optional[str] = None

    buyer_name: Optional[str] = None
    buyer_gstin: Optional[str] = Field(
        default=None,
        description="Buyer/recipient 15-character GSTIN when printed on the document",
    )
    buyer_address: Optional[str] = None

    currency: Optional[str] = Field(default=None, description="ISO 4217, e.g. 'INR'")
    subtotal: Optional[float] = Field(
        default=None,
        description=(
            "Taxable amount / taxable value / assessable value / subtotal before GST. "
            "These labels mean the same field — map any of them here."
        ),
    )
    tax_amount: Optional[float] = Field(
        default=None,
        description="Overall tax total if shown as a single figure (CGST+SGST or IGST)",
    )
    cgst_amount: Optional[float] = Field(
        default=None, description="Central GST amount for intra-state supply"
    )
    sgst_amount: Optional[float] = Field(
        default=None, description="State/UT GST amount for intra-state supply"
    )
    igst_amount: Optional[float] = Field(
        default=None, description="Integrated GST amount for inter-state supply"
    )
    cgst_percent: Optional[float] = Field(
        default=None, description="Document-level CGST rate, e.g. 9.0"
    )
    sgst_percent: Optional[float] = Field(
        default=None, description="Document-level SGST/UTGST rate, e.g. 9.0"
    )
    igst_percent: Optional[float] = Field(
        default=None,
        description="Document-level IGST rate as a number, e.g. 18.0 for 'IGST @ 18%' or Tax Rate 18%",
    )
    supply_type: Optional[str] = Field(
        default=None,
        description="intra_state when CGST+SGST apply; inter_state when IGST applies",
    )
    total_amount: Optional[float] = None

    line_items: list[LineItem] = Field(default_factory=list)

    fields_model_could_not_read: list[str] = Field(
        default_factory=list,
        description=(
            "Names of expected fields that were present on the document but "
            "illegible/ambiguous (e.g. due to a smudge or fold). Do NOT list "
            "fields that were simply absent from the document."
        ),
    )


class GstinFocusedExtraction(BaseModel):
    """Second-pass schema: read only supplier and buyer GSTIN from the document."""

    vendor_gstin: Optional[str] = Field(
        default=None,
        description="15-character supplier/seller GSTIN from the vendor block",
    )
    buyer_gstin: Optional[str] = Field(
        default=None,
        description="15-character buyer/recipient GSTIN from Bill To / buyer block",
    )


class FieldConfidence(BaseModel):
    """Per-field confidence, 0-1, produced by our own scoring layer (not the model)."""

    field: str
    score: float
    reason: str


class OCRExtractionResult(BaseModel):
    """
    Top-level result returned by GPT4VisionOCR.extract().
    This is what the rest of the pipeline (Phase 3 onward) should consume.
    """

    source_file: str
    page_count: int
    model_used: str

    data: InvoiceExtraction

    overall_confidence: float = Field(
        description="0-1 aggregate confidence score from confidence.py"
    )
    field_confidences: list[FieldConfidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    raw_model_response: Optional[str] = Field(
        default=None,
        description="Raw JSON string from the model, kept for audit/debug only",
    )
