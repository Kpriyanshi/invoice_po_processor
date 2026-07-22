"""
Core module: sends invoice/PO pages to GPT-4o vision and gets back a
validated, structured InvoiceExtraction object.

Usage:
    from ocr_module import GPT4VisionOCR

    ocr = GPT4VisionOCR()
    result = await ocr.extract("invoice_0001.pdf")
    print(result.data.total_amount, result.overall_confidence)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError

from .config import OCRSettings
from .confidence import score_extraction
from .gstin_validation import (
    find_all_valid_gstins_in_text,
    find_valid_gstin_in_text,
    repair_gstin,
    repair_gstin_candidates,
    validate_gstin,
)
from .exceptions import LowConfidenceError, VisionAPIError
from .preprocessing import load_pages_as_base64
from .schemas import (
    GstinFocusedExtraction,
    InvoiceExtraction,
    LineItem,
    OCRExtractionResult,
)

logger = logging.getLogger(__name__)

def _coerce_gstin(value: str | None) -> str | None:
    result = validate_gstin(value)
    return result.normalized if result.is_valid else None


def _find_gstin(text: str | None) -> str | None:
    return find_valid_gstin_in_text(text)


def _strip_gstin_from_name(name: str | None, gstin: str | None) -> str | None:
    if not name or not gstin:
        return name
    cleaned = name
    for variant in (gstin, gstin.lower(), f"({gstin})", f"({gstin.lower()})"):
        cleaned = cleaned.replace(variant, "")
    return " ".join(cleaned.split()).strip() or name


def _gstin_needs_focused_pass(data: InvoiceExtraction) -> bool:
    vendor_ok = bool(
        _coerce_gstin(data.vendor_gstin) or repair_gstin(data.vendor_gstin)
    )
    buyer_ok = bool(_coerce_gstin(data.buyer_gstin) or repair_gstin(data.buyer_gstin))
    return not vendor_ok or not buyer_ok


def _resolve_gstin(
    raw_value: str | None,
    address: str | None,
    name: str | None,
    focused_value: str | None = None,
) -> str | None:
    for candidate in (raw_value, focused_value):
        coerced = _coerce_gstin(candidate)
        if coerced:
            return coerced
        repaired = repair_gstin(candidate)
        if repaired:
            return repaired

    for text in (address, name):
        found = _find_gstin(text)
        if found:
            return found

    return None


def _normalize_extraction(
    data: InvoiceExtraction,
    *,
    focused: GstinFocusedExtraction | None = None,
) -> InvoiceExtraction:
    raw_vendor = data.vendor_gstin
    raw_buyer = data.buyer_gstin
    focused_vendor = focused.vendor_gstin if focused else None
    focused_buyer = focused.buyer_gstin if focused else None

    vendor_gstin = _resolve_gstin(
        raw_vendor,
        data.vendor_address,
        data.vendor_name,
        focused_vendor,
    )
    buyer_gstin = _resolve_gstin(
        raw_buyer,
        data.buyer_address,
        data.buyer_name,
        focused_buyer,
    )

    if not vendor_gstin or not buyer_gstin:
        blobs = [
            data.vendor_address,
            data.vendor_name,
            data.buyer_address,
            data.buyer_name,
        ]
        candidates: list[str] = []
        for blob in blobs:
            candidates.extend(find_all_valid_gstins_in_text(blob))
        if focused_vendor:
            candidates.append(focused_vendor)
        if focused_buyer:
            candidates.append(focused_buyer)
        deduped: list[str] = []
        for candidate in candidates:
            coerced = _coerce_gstin(candidate)
            if coerced and coerced not in deduped:
                deduped.append(coerced)
        if not vendor_gstin and deduped:
            vendor_gstin = deduped[0]
        if not buyer_gstin and deduped:
            buyer_gstin = deduped[-1] if len(deduped) > 1 else None
            if buyer_gstin == vendor_gstin:
                buyer_gstin = None

    vendor_name = _strip_gstin_from_name(data.vendor_name, vendor_gstin)

    supply_type = data.supply_type
    if vendor_gstin and buyer_gstin and len(vendor_gstin) >= 2 and len(buyer_gstin) >= 2:
        if vendor_gstin[:2] == buyer_gstin[:2]:
            supply_type = "intra_state"
        else:
            supply_type = "inter_state"
    elif supply_type is None:
        if data.igst_amount is not None or data.igst_percent is not None:
            supply_type = "inter_state"
        elif data.cgst_amount is not None or data.sgst_amount is not None:
            supply_type = "intra_state"

    # Taxable Amount and Subtotal are the same concept.
    subtotal = data.subtotal
    igst_amount = data.igst_amount
    cgst_amount = data.cgst_amount
    sgst_amount = data.sgst_amount
    tax_amount = data.tax_amount
    total_amount = data.total_amount

    if tax_amount is None:
        if igst_amount is not None:
            tax_amount = igst_amount
        elif cgst_amount is not None or sgst_amount is not None:
            tax_amount = (cgst_amount or 0.0) + (sgst_amount or 0.0)

    if subtotal is None and total_amount is not None and tax_amount is not None:
        subtotal = round(total_amount - tax_amount, 2)
    if total_amount is None and subtotal is not None and tax_amount is not None:
        total_amount = round(subtotal + tax_amount, 2)

    igst_percent = data.igst_percent
    cgst_percent = data.cgst_percent
    sgst_percent = data.sgst_percent
    if (
        supply_type == "inter_state"
        and igst_percent is None
        and cgst_percent is not None
        and sgst_percent is not None
    ):
        igst_percent = cgst_percent + sgst_percent
    if (
        supply_type == "intra_state"
        and igst_percent is not None
        and cgst_percent is None
        and sgst_percent is None
    ):
        half = round(igst_percent / 2.0, 2)
        cgst_percent = half
        sgst_percent = half

    line_items: list[LineItem] = []
    for item in data.line_items:
        name = (item.description or item.product_name or "").strip()
        if not name:
            continue
        unit_price = item.unit_price
        if unit_price is None and item.list_price is not None:
            unit_price = item.list_price

        line_igst = item.igst_percent
        line_cgst = item.cgst_percent
        line_sgst = item.sgst_percent
        line_tax_rate = item.tax_rate_percent

        if line_igst is None and line_tax_rate is not None and supply_type == "inter_state":
            line_igst = line_tax_rate
        if line_cgst is None and line_sgst is None and line_tax_rate is not None and supply_type == "intra_state":
            half = round(line_tax_rate / 2.0, 2)
            line_cgst = half
            line_sgst = half
        if line_igst is None and supply_type == "inter_state":
            line_igst = igst_percent
        if line_cgst is None and supply_type == "intra_state":
            line_cgst = cgst_percent
        if line_sgst is None and supply_type == "intra_state":
            line_sgst = sgst_percent

        line_total = item.line_total
        # If the model put tax-inclusive grand total on the only line, prefer taxable subtotal.
        if (
            line_total is not None
            and total_amount is not None
            and subtotal is not None
            and abs(line_total - total_amount) <= max(1.0, abs(total_amount) * 0.01)
            and abs(line_total - subtotal) > max(1.0, abs(subtotal) * 0.01)
        ):
            line_total = subtotal
            if unit_price is not None and abs(unit_price - total_amount) <= max(
                1.0, abs(total_amount) * 0.01
            ):
                unit_price = subtotal

        line_items.append(
            item.model_copy(
                update={
                    "description": name,
                    "product_name": item.product_name or name,
                    "unit_price": unit_price,
                    "igst_percent": line_igst,
                    "cgst_percent": line_cgst,
                    "sgst_percent": line_sgst,
                    "line_total": line_total,
                }
            )
        )

    if igst_percent is None and line_items:
        line_rates = {li.igst_percent for li in line_items if li.igst_percent is not None}
        if len(line_rates) == 1:
            igst_percent = line_rates.pop()
    if cgst_percent is None and line_items:
        line_rates = {li.cgst_percent for li in line_items if li.cgst_percent is not None}
        if len(line_rates) == 1:
            cgst_percent = line_rates.pop()
    if sgst_percent is None and line_items:
        line_rates = {li.sgst_percent for li in line_items if li.sgst_percent is not None}
        if len(line_rates) == 1:
            sgst_percent = line_rates.pop()

    return data.model_copy(
        update={
            "vendor_name": vendor_name,
            "vendor_gstin": vendor_gstin,
            "buyer_gstin": buyer_gstin,
            "supply_type": supply_type,
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "igst_amount": igst_amount,
            "cgst_amount": cgst_amount,
            "sgst_amount": sgst_amount,
            "igst_percent": igst_percent,
            "cgst_percent": cgst_percent,
            "sgst_percent": sgst_percent,
            "total_amount": total_amount,
            "line_items": line_items,
        }
    )

_SYSTEM_PROMPT = """\
You are a precise document data extraction engine for an accounts-payable \
pipeline. You will be shown one or more page images from a single invoice \
or purchase order (multiple images = multiple pages of the SAME document).

Extract the fields defined by the provided schema exactly as they appear \
on the document. Rules:
- Never guess or infer a value that is not visibly printed on the document.
- If a field is not present on the document at all, return null for it.
- If a field IS present but you cannot read it confidently (smudge, glare, \
fold, cut-off edge), still make your best-effort reading, but add the \
field's name to fields_model_could_not_read.
- Set document_type to the best-fitting normalized category and store the \
exact visible title like "Tax Invoice" or "Purchase Order" in document_label.
- invoice_date is the invoice/bill date. order_date is the order/PO date if \
the document shows one separately.
- GSTIN: extract the 15-character supplier GSTIN into vendor_gstin and the \
buyer GSTIN into buyer_gstin. Copy characters exactly; GSTIN must pass the \
official mod-36 checksum. Do not embed GSTIN inside vendor_name; keep names \
and GSTINs in separate fields. The first 2 digits of GSTIN are the state code.
- Tax type by state (Indian GST): if seller and buyer GSTIN state codes are \
the SAME (intra-state), extract CGST and SGST amounts/rates. If state codes \
DIFFER (inter-state), extract IGST amount/rate. Set supply_type to \
intra_state or inter_state accordingly. Do not invent the other tax type.
- subtotal is the Taxable Amount / Taxable Value / Assessable Value / Subtotal \
before GST — these labels mean the SAME field. Map any of them to subtotal.
- For EVERY product row in the items/line-items table you MUST extract: \
description (item name), quantity, unit_price (rate per unit BEFORE tax), and \
line_total (taxable line amount BEFORE tax). Never put the invoice grand total \
into unit_price or line_total. If there is only one name column, copy that text \
into both description and product_name.
- unit_price is the per-unit rate before tax (columns labeled Rate, Unit \
Price, Price/Unit, etc.). list_price is only when a separate MRP/list \
column exists.
- Extract tax rates from Tax Rate / CGST% / SGST% / IGST% columns into the \
matching percent fields. On line items, also set tax_rate_percent when a \
single overall GST rate is shown.
- Normalize dates to ISO 8601 (YYYY-MM-DD).
- Normalize amounts to plain numbers (no currency symbols or thousands \
separators).
- If the document spans multiple pages, merge line items from all pages \
into a single list, in order.
"""

_GSTIN_FOCUS_PROMPT = """\
You extract ONLY GSTIN numbers from invoice images. Read the supplier/seller \
GSTIN and the buyer/recipient GSTIN character by character. Copy exactly what \
is printed. Each GSTIN is 15 alphanumeric characters. Do not guess. If a \
GSTIN is not visible, return null for that field.
"""


class GPT4VisionOCR:
    def __init__(self, settings: OCRSettings | None = None):
        self.settings = settings or OCRSettings()
        if not self.settings.openai_api_key:
            raise ValueError(
                "No OpenAI API key configured. Set OCR_OPENAI_API_KEY in the "
                "environment or pass an OCRSettings instance explicitly."
            )
        self._client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            timeout=self.settings.request_timeout_seconds,
        )

    async def extract(
        self,
        file_path: str,
        raise_on_low_confidence: bool = False,
    ) -> OCRExtractionResult:
        """
        Runs OCR + structured extraction on a single file (image or PDF).

        If raise_on_low_confidence=True and the resulting overall_confidence
        is below settings.low_confidence_threshold, raises LowConfidenceError
        instead of returning -- useful if you want low-confidence documents
        routed straight to a human-review queue rather than continuing
        through Phase 3/4 automatically.
        """
        pages_b64 = load_pages_as_base64(file_path, self.settings)

        parsed, raw_json = await self._call_model_with_retries(pages_b64)

        needs_gstin_pass = (
            self.settings.gstin_focused_pass and _gstin_needs_focused_pass(parsed)
        )
        focused: GstinFocusedExtraction | None = None
        if needs_gstin_pass:
            focused = await self._call_gstin_focused_pass(pages_b64)

        parsed = _normalize_extraction(parsed, focused=focused)

        overall_confidence, field_confidences, warnings = score_extraction(parsed)

        if (
            raise_on_low_confidence
            and overall_confidence < self.settings.low_confidence_threshold
        ):
            raise LowConfidenceError(
                f"overall_confidence={overall_confidence} is below threshold "
                f"{self.settings.low_confidence_threshold} for '{file_path}'"
            )

        return OCRExtractionResult(
            source_file=file_path,
            page_count=len(pages_b64),
            model_used=self.settings.model_name,
            data=parsed,
            overall_confidence=overall_confidence,
            field_confidences=field_confidences,
            warnings=warnings,
            raw_model_response=raw_json,
        )

    async def _call_model_with_retries(
        self, pages_b64: list[str]
    ) -> tuple[InvoiceExtraction, str]:
        image_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
            }
            for b64 in pages_b64
        ]

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Extract all fields from this {len(pages_b64)}-page document. "
                            "Include vendor_gstin, buyer_gstin, subtotal (Taxable Amount), "
                            "supply_type, CGST/SGST or IGST amounts and rates as printed, "
                            "and for each line item product name, quantity, unit_price "
                            "(before tax), tax rates, and taxable line_total."
                        ),
                    },
                    *image_content,
                ],
            },
        ]

        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                start = time.monotonic()
                completion = await self._client.chat.completions.parse(
                    model=self.settings.model_name,
                    messages=messages,
                    response_format=InvoiceExtraction,
                    temperature=0,
                )
                elapsed = time.monotonic() - start
                logger.info(
                    "GPT-4 Vision extraction succeeded in %.2fs (attempt %d)",
                    elapsed,
                    attempt,
                )

                choice = completion.choices[0]
                if choice.message.refusal:
                    raise VisionAPIError(f"Model refused: {choice.message.refusal}")

                parsed = choice.message.parsed
                if parsed is None:
                    raise VisionAPIError("Model response did not match the expected schema")

                raw_json = json.dumps(json.loads(choice.message.content), indent=None)
                return parsed, raw_json

            except (RateLimitError, APITimeoutError, APIError) as exc:
                last_error = exc
                if attempt == self.settings.max_retries:
                    break
                backoff_seconds = 2 ** (attempt - 1)
                logger.warning(
                    "GPT-4 Vision call failed (attempt %d/%d): %s. Retrying in %ds.",
                    attempt,
                    self.settings.max_retries,
                    exc,
                    backoff_seconds,
                )
                await asyncio.sleep(backoff_seconds)

        raise VisionAPIError(
            f"GPT-4 Vision extraction failed after {self.settings.max_retries} attempts"
        ) from last_error

    async def _call_gstin_focused_pass(
        self, pages_b64: list[str]
    ) -> GstinFocusedExtraction | None:
        """Second pass on page 1 when GSTIN is missing or checksum-invalid."""
        if not pages_b64:
            return None

        image_content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{pages_b64[0]}",
                    "detail": "high",
                },
            }
        ]
        messages = [
            {"role": "system", "content": _GSTIN_FOCUS_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Read vendor_gstin from the seller/supplier block and "
                            "buyer_gstin from Bill To / buyer / consignee block."
                        ),
                    },
                    *image_content,
                ],
            },
        ]

        try:
            completion = await self._client.chat.completions.parse(
                model=self.settings.model_name,
                messages=messages,
                response_format=GstinFocusedExtraction,
                temperature=0,
            )
        except (RateLimitError, APITimeoutError, APIError) as exc:
            logger.warning("GSTIN focused pass failed: %s", exc)
            return None

        choice = completion.choices[0]
        if choice.message.refusal or choice.message.parsed is None:
            return None
        return choice.message.parsed
