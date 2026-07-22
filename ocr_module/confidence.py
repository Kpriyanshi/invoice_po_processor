"""
Confidence scoring layer.

This mirrors the "Python confidence scoring layer validates OCR quality"
step from the original Phase 2 design -- previously scoring EasyOCR/
Tesseract character-level confidence, here instead scoring the plausibility
and completeness of the structured object GPT-4 Vision returned.

Deliberately independent of anything the model "says" about its own
confidence (LLMs are not well-calibrated at self-reporting this) -- it's
consistency and completeness checks over the data itself.
"""

from __future__ import annotations

from datetime import date

from .gstin_validation import validate_gstin
from .schemas import FieldConfidence, InvoiceExtraction

_CRITICAL_FIELDS = ["invoice_number", "invoice_date", "vendor_name", "total_amount"]
_IMPORTANT_FIELDS = [
    "vendor_gstin",
    "subtotal",
    "po_number",
    "order_date",
]

_AMOUNT_TOLERANCE_FRACTION = 0.01  # 1% rounding slack


def _effective_tax_amount(data: InvoiceExtraction) -> float | None:
    if data.tax_amount is not None:
        return data.tax_amount
    if data.igst_amount is not None:
        return data.igst_amount
    if data.cgst_amount is not None or data.sgst_amount is not None:
        return (data.cgst_amount or 0.0) + (data.sgst_amount or 0.0)
    return None


def _gst_type_from_gstin(data: InvoiceExtraction) -> str | None:
    if (
        data.vendor_gstin
        and data.buyer_gstin
        and len(data.vendor_gstin) >= 2
        and len(data.buyer_gstin) >= 2
    ):
        if data.vendor_gstin[:2] == data.buyer_gstin[:2]:
            return "intra_state"
        return "inter_state"
    return data.supply_type


def _validate_gstin_field(
    field_name: str,
    gstin_value: str | None,
    field_scores: list[FieldConfidence],
    warnings: list[str],
) -> None:
    if not gstin_value:
        return

    result = validate_gstin(gstin_value)
    if result.is_valid:
        gstin_score = 1.0
        reason = result.reason
    else:
        gstin_score = 0.1
        reason = result.reason
        warnings.append(
            f"{field_name} '{gstin_value}' failed GSTIN validation: {result.reason}"
        )

    field_scores.append(
        FieldConfidence(
            field=f"{field_name}_format",
            score=gstin_score,
            reason=reason,
        )
    )


def score_extraction(
    data: InvoiceExtraction,
) -> tuple[float, list[FieldConfidence], list[str]]:
    """
    Returns (overall_confidence, per_field_confidences, warnings).
    """
    field_scores: list[FieldConfidence] = []
    warnings: list[str] = []

    unreadable = set(f.lower() for f in data.fields_model_could_not_read)

    # --- Completeness of critical fields ---
    for field in _CRITICAL_FIELDS:
        value = getattr(data, field)
        if value is None:
            score = 0.0
            reason = "missing"
            warnings.append(f"Critical field '{field}' is missing")
        elif field in unreadable:
            score = 0.3
            reason = "model flagged as illegible"
            warnings.append(f"Critical field '{field}' was flagged as illegible")
        else:
            score = 1.0
            reason = "present"
        field_scores.append(FieldConfidence(field=field, score=score, reason=reason))

    # --- Completeness of important-but-not-critical fields ---
    for field in _IMPORTANT_FIELDS:
        value = getattr(data, field)
        if value is None:
            score = 0.4
            reason = "missing (non-critical)"
        elif field in unreadable:
            score = 0.5
            reason = "model flagged as illegible"
        else:
            score = 1.0
            reason = "present"
        field_scores.append(FieldConfidence(field=field, score=score, reason=reason))

    # --- Format validation: GSTIN ---
    _validate_gstin_field("vendor_gstin", data.vendor_gstin, field_scores, warnings)
    _validate_gstin_field("buyer_gstin", data.buyer_gstin, field_scores, warnings)

    # --- GST type consistency from seller/buyer state codes ---
    gst_type = _gst_type_from_gstin(data)
    if gst_type == "inter_state":
        if data.igst_amount is not None or data.igst_percent is not None:
            field_scores.append(
                FieldConfidence(field="gst_type", score=1.0, reason="inter_state IGST present")
            )
        else:
            warnings.append(
                "Seller and buyer are in different states (inter-state); expected IGST"
            )
            field_scores.append(
                FieldConfidence(field="gst_type", score=0.3, reason="missing IGST for inter_state")
            )
        if data.cgst_amount is not None or data.sgst_amount is not None:
            warnings.append(
                "CGST/SGST present on an inter-state invoice; usually only IGST applies"
            )
    elif gst_type == "intra_state":
        if data.cgst_amount is not None or data.sgst_amount is not None:
            field_scores.append(
                FieldConfidence(field="gst_type", score=1.0, reason="intra_state CGST/SGST present")
            )
        else:
            warnings.append(
                "Seller and buyer are in the same state (intra-state); expected CGST and SGST"
            )
            field_scores.append(
                FieldConfidence(
                    field="gst_type", score=0.3, reason="missing CGST/SGST for intra_state"
                )
            )
        if data.igst_amount is not None:
            warnings.append(
                "IGST present on an intra-state invoice; usually CGST+SGST apply instead"
            )

    # --- Format validation: date not in the future ---
    if data.invoice_date and data.invoice_date > date.today():
        warnings.append(f"invoice_date '{data.invoice_date}' is in the future")
        field_scores.append(
            FieldConfidence(field="invoice_date_plausibility", score=0.1, reason="future date")
        )

    # --- Consistency: subtotal + tax ≈ total ---
    effective_tax_amount = _effective_tax_amount(data)
    if (
        data.subtotal is not None
        and effective_tax_amount is not None
        and data.total_amount is not None
    ):
        expected_total = data.subtotal + effective_tax_amount
        tolerance = max(1.0, abs(data.total_amount) * _AMOUNT_TOLERANCE_FRACTION)
        if abs(expected_total - data.total_amount) <= tolerance:
            consistency_score = 1.0
        else:
            consistency_score = 0.2
            warnings.append(
                f"subtotal ({data.subtotal}) + tax ({effective_tax_amount}) = "
                f"{expected_total}, which does not match total_amount "
                f"({data.total_amount})"
            )
        field_scores.append(
            FieldConfidence(
                field="amount_consistency", score=consistency_score, reason="arithmetic check"
            )
        )

    # --- Consistency: line items sum ≈ subtotal ---
    if data.line_items and data.subtotal is not None:
        line_total_sum = sum(li.line_total for li in data.line_items if li.line_total is not None)
        if line_total_sum > 0:
            tolerance = max(1.0, abs(data.subtotal) * _AMOUNT_TOLERANCE_FRACTION)
            if abs(line_total_sum - data.subtotal) <= tolerance:
                line_sum_score = 1.0
            else:
                line_sum_score = 0.4
                warnings.append(
                    f"sum of line item totals ({line_total_sum}) does not match "
                    f"subtotal ({data.subtotal})"
                )
            field_scores.append(
                FieldConfidence(
                    field="line_items_sum_check", score=line_sum_score, reason="arithmetic check"
                )
            )

    # --- Line items: names and unit prices ---
    if data.line_items:
        for index, item in enumerate(data.line_items, start=1):
            prefix = f"line_items[{index}]"
            if not (item.description or item.product_name):
                warnings.append(f"{prefix}: item name is missing")
                field_scores.append(
                    FieldConfidence(
                        field=f"{prefix}.description",
                        score=0.0,
                        reason="missing item name",
                    )
                )
            if item.unit_price is None:
                warnings.append(f"{prefix}: unit_price is missing")
                field_scores.append(
                    FieldConfidence(
                        field=f"{prefix}.unit_price",
                        score=0.3,
                        reason="missing unit price",
                    )
                )

    if not field_scores:
        return 0.0, [], ["No scorable fields were extracted at all"]

    overall = sum(fs.score for fs in field_scores) / len(field_scores)
    return round(overall, 3), field_scores, warnings
