from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_CURRENCY_RE = (
    r"(?:₹|INR|Rs\.?|USD|\$)?\s*"
    r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)"
)
_AMOUNT_LINE = re.compile(
    r"^[\{\<\[]?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\s*[\}\>\]]?\s*$"
)
_GSTIN_BODY = re.compile(
    r"\b(?:GSTIN(?:\s*/\s*UIN)?|GST\s*(?:IN|No\.?|Number)?)\s*[:\;\.]?\s*([0-9A-Z]{15})\b",
    re.IGNORECASE,
)
_GSTIN_LOOSE = re.compile(
    r"\b(?:GSTIN(?:\s*/\s*UIN)?|GSIN|GST\s*(?:IN|No\.?|Number)?)\s*[:\;\.]?\s*([0-9A-ZIlO\s]{15,17})\b",
    re.IGNORECASE,
)

# Section start / end markers for product table (aliases)
_LINE_ITEM_START = (
    r"ITEMS|ITEM\s*DETAILS|DESCRIPTION\s*OF\s*GOODS|DESCRIPTION|PARTICULARS|"
    r"PRODUCT\s*DETAILS|PRODUCTS?|GOODS"
)
_LINE_ITEM_END = (
    r"SUB[\s\-]*TOTAL|SUBTOTAL|TAXABLE\s*(?:VALUE|AMOUNT)|"
    r"TOTAL\s*(?:BEFORE\s*)?TAX|CGST|SGST|IGST|GST\s*AMOUNT|TAX\s*TOTAL|"
    r"GRAND\s*TOTAL|TOTAL\s*AMOUNT|NET\s*AMOUNT"
)


@dataclass
class ExtractedField:
    value: str | None
    confidence: float
    evidence: str | None = None


def _normalize_amount(raw: str) -> str:
    s = (
        raw.strip()
        .replace("{", "")
        .replace("}", "")
        .replace("<", "")
        .replace(">", "")
        .replace("[", "")
        .replace("]", "")
    )
    return s.strip()


def _normalize_gstin(candidate: str) -> str | None:
    """
    Normalize GSTIN with position-aware OCR fixes.
    Structure: SS + PAN(5 letters + 4 digits + 1 letter) + entity + Z + checksum
    Only rewrite digit slots (do not turn valid PAN letter L into 1).
    """
    s = re.sub(r"\s+", "", candidate.upper())
    if len(s) != 15:
        return None

    digit_fix = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"}
    chars = list(s)
    for i in (0, 1, 7, 8, 9, 10, 12):
        chars[i] = digit_fix.get(chars[i], chars[i])
    if chars[13] in "2Zz":
        chars[13] = "Z"

    s = "".join(chars)
    if re.fullmatch(r"[0-9A-Z]{15}", s):
        return s
    return None


def _extract_gstin(text: str) -> tuple[str | None, str | None]:
    for pat in (_GSTIN_BODY, _GSTIN_LOOSE):
        m = pat.search(text)
        if m:
            norm = _normalize_gstin(m.group(1))
            if norm:
                return norm, m.group(0).strip()
    return None, None


def _extract_invoice_no(text: str) -> tuple[str | None, str | None]:
    patterns = [
        re.compile(
            r"(?:Tax\s*)?Invoice\s*(?:No\.?|Number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/]+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:Bill|Inv)\s*(?:No\.?|Number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/]+)",
            re.IGNORECASE,
        ),
        # OCR often splits "Invoice" then number on next line
        re.compile(r"Invoice\s*\n\s*([A-Z0-9][A-Z0-9\-\/]+)", re.IGNORECASE),
        re.compile(r"\bINV[\-\s#:]*([A-Z0-9][A-Z0-9\-\/]+)", re.IGNORECASE),
    ]
    skip = {"invoice", "date", "no", "number", "bill", "tax", "inv"}
    for p in patterns:
        m = p.search(text)
        if m:
            val = m.group(1).strip()
            if val.lower() not in skip:
                return val, m.group(0).strip()
    return None, None


def _extract_invoice_date(text: str) -> tuple[str | None, str | None]:
    date_token = r"([0-3]?\d[/\-\.][0-1]?\d[/\-\.](?:\d{4}|\d{2}))"
    patterns = [
        re.compile(
            rf"(?:Invoice|Inv|Bill)\s*Date\s*[:\-]?\s*{date_token}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\bDated\s*[:\-]?\s*{date_token}\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\bDate\s*[:\-]?\s*{date_token}\b",
            re.IGNORECASE,
        ),
    ]
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(1).strip(), m.group(0).strip()
    return None, None


def _pick_amount_after_label(text: str, labels: list[str]) -> tuple[str | None, str | None]:
    for label in labels:
        pat = re.compile(
            rf"\b{label}\s*[:\-]?\s*[\{{\<\[]?\s*"
            rf"([0-9]{{1,3}}(?:,[0-9]{{3}})*(?:\.[0-9]{{1,2}})?|[0-9]+(?:\.[0-9]{{1,2}})?)",
            re.IGNORECASE,
        )
        m = pat.search(text)
        if m:
            return _normalize_amount(m.group(1)), m.group(0).strip()
        pat_nl = re.compile(
            rf"\b{label}\s*\n+\s*[\{{\<\[]?\s*"
            rf"([0-9]{{1,3}}(?:,[0-9]{{3}})*(?:\.[0-9]{{1,2}})?|[0-9]+(?:\.[0-9]{{1,2}})?)",
            re.IGNORECASE,
        )
        m = pat_nl.search(text)
        if m:
            return _normalize_amount(m.group(1)), m.group(0).strip()
    return None, None


def _is_header_line(line: str) -> bool:
    u = line.upper().strip().rstrip(":")
    return u in {
        "ITEMS",
        "ITEM",
        "ITEM DETAILS",
        "DESCRIPTION",
        "DESCRIPTION OF GOODS",
        "PARTICULARS",
        "PRODUCT",
        "PRODUCTS",
        "PRODUCT DETAILS",
        "GOODS",
        "QTY",
        "QTY.",
        "QTY:",
        "QUANTITY",
        "RATE",
        "LIST",
        "LIST PRICE",
        "UNIT PRICE",
        "UNIT RATE",
        "PRICE",
        "AMOUNT",
        "TOTAL",
        "UNIT",
        "HSN",
        "SAC",
        "HSN/SAC",
    }


def _is_unit_line(line: str) -> bool:
    return line.upper().strip() in {
        "PCS",
        "PC",
        "NOS",
        "NO",
        "NOS.",
        "UNIT",
        "UNITS",
        "EA",
        "EACH",
        "KG",
        "KGS",
        "LTR",
        "LT",
        "BOX",
        "SET",
        "PAIR",
        "PKT",
        "PACK",
    }


def _is_amount_line(line: str) -> bool:
    return _AMOUNT_LINE.match(line.strip()) is not None


def extract_line_items(raw_text: str, avg_ocr_conf: float) -> list[dict[str, Any]]:
    """
    Parse product rows between Description/ITEMS (and aliases) and Subtotal/Tax/Total markers.

    Each item:
      description, quantity, unit, unit_price (rate/list/price), line_total (amount)
    """
    block_match = re.search(
        rf"(?is)(?:{_LINE_ITEM_START})\s*(.*?)\s*(?:{_LINE_ITEM_END})",
        raw_text,
    )
    if not block_match:
        return []

    block = block_match.group(1)
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    items: list[dict[str, Any]] = []
    i = 0
    conf = max(0.0, min(1.0, avg_ocr_conf + 0.05))

    while i < len(lines):
        if _is_header_line(lines[i]) or _is_unit_line(lines[i]) or _is_amount_line(lines[i]):
            i += 1
            continue

        desc_parts: list[str] = []
        while i < len(lines):
            ln = lines[i]
            if _is_header_line(ln):
                i += 1
                continue
            if _is_unit_line(ln) or _is_amount_line(ln):
                break
            desc_parts.append(ln)
            i += 1

        description = " ".join(desc_parts).strip()
        if not description:
            continue

        unit = None
        if i < len(lines) and _is_unit_line(lines[i]):
            unit = lines[i].upper()
            i += 1

        amounts: list[str] = []
        while i < len(lines) and _is_amount_line(lines[i]):
            m = _AMOUNT_LINE.match(lines[i].strip())
            if m:
                amounts.append(_normalize_amount(m.group(1)))
            i += 1

        quantity: str | None = None
        unit_price: str | None = None
        line_total: str | None = None

        if len(amounts) >= 3:
            quantity, unit_price, line_total = amounts[0], amounts[1], amounts[2]
        elif len(amounts) == 2:
            # Common OCR layout: RATE then AMOUNT, qty missing → assume 1
            quantity = "1"
            unit_price, line_total = amounts[0], amounts[1]
        elif len(amounts) == 1:
            quantity = "1"
            unit_price = line_total = amounts[0]

        items.append(
            {
                "description": description,
                "quantity": quantity,
                "unit": unit,
                "unit_price": unit_price,
                "line_total": line_total,
                "confidence": round(conf, 4),
            }
        )

    return items


def extract_invoice_fields(raw_text: str, line_confs: list[float]) -> dict[str, ExtractedField]:
    """
    Rule-based header extraction from OCR text.
    Recognizes common label aliases that mean the same field.
    """
    text = raw_text
    avg_ocr_conf = (sum(line_confs) / len(line_confs)) if line_confs else 0.0

    def field_conf(found: bool, boost: float = 0.15) -> float:
        if not found:
            return 0.0
        return max(0.0, min(1.0, avg_ocr_conf + boost))

    gstin, gstin_ev = _extract_gstin(text)
    invoice_no, invoice_no_ev = _extract_invoice_no(text)
    invoice_date, date_ev = _extract_invoice_date(text)

    subtotal, subtotal_ev = _pick_amount_after_label(
        text,
        [
            "SUBTOTAL",
            "SUB TOTAL",
            "SUB-TOTAL",
            "SUB TOTAL",
            "TAXABLE VALUE",
            "TAXABLE AMOUNT",
            "TOTAL BEFORE TAX",
        ],
    )

    # Prefer specific GST breakup labels, then generic tax total
    igst, igst_ev = _pick_amount_after_label(text, ["IGST", "I\\.G\\.S\\.T"])
    cgst, cgst_ev = _pick_amount_after_label(text, ["CGST", "C\\.G\\.S\\.T"])
    sgst, sgst_ev = _pick_amount_after_label(text, ["SGST", "S\\.G\\.S\\.T"])
    tax_total, tax_ev = _pick_amount_after_label(
        text,
        [
            "TAX TOTAL",
            "TOTAL TAX",
            "TOTAL GST",
            "GST AMOUNT",
            "GST TOTAL",
            "TAX AMOUNT",
            "GST",
            "TAX",
        ],
    )
    # If breakup found but no tax_total, sum is not attempted (OCR text only);
    # fall back to IGST/CGST+SGST evidence for tax_total when only one exists.
    if tax_total is None:
        if igst is not None:
            tax_total, tax_ev = igst, igst_ev
        elif cgst is not None and sgst is not None:
            tax_total, tax_ev = cgst, cgst_ev  # evidence from cgst; values kept separate

    total, total_ev = _pick_amount_after_label(
        text,
        [
            "GRAND TOTAL",
            "TOTAL AMOUNT",
            "NET AMOUNT",
            "INVOICE TOTAL",
            "AMOUNT PAYABLE",
            "NET PAYABLE",
            "TOTAL PAYABLE",
        ],
    )
    if not total:
        for p in [
            re.compile(r"\b(grand\s*total\s*[:\-]?\s*" + _CURRENCY_RE + r")\b", re.IGNORECASE),
            re.compile(r"\b(total\s*amount\s*[:\-]?\s*" + _CURRENCY_RE + r")\b", re.IGNORECASE),
        ]:
            m = p.search(text)
            if m and m.lastindex:
                total = _normalize_amount(m.group(m.lastindex))
                total_ev = m.group(0).strip()
                break

    fields: dict[str, ExtractedField] = {
        "gstin": ExtractedField(gstin, field_conf(gstin is not None, 0.20), gstin_ev),
        "invoice_no": ExtractedField(invoice_no, field_conf(invoice_no is not None, 0.20), invoice_no_ev),
        "invoice_date": ExtractedField(invoice_date, field_conf(invoice_date is not None, 0.10), date_ev),
        "subtotal": ExtractedField(subtotal, field_conf(subtotal is not None, 0.15), subtotal_ev),
        "igst": ExtractedField(igst, field_conf(igst is not None, 0.10), igst_ev),
        "cgst": ExtractedField(cgst, field_conf(cgst is not None, 0.10), cgst_ev),
        "sgst": ExtractedField(sgst, field_conf(sgst is not None, 0.10), sgst_ev),
        "tax_total": ExtractedField(tax_total, field_conf(tax_total is not None, 0.10), tax_ev),
        # Aliases for the same payable amount
        "grand_total": ExtractedField(total, field_conf(total is not None, 0.15), total_ev),
        "total_amount": ExtractedField(total, field_conf(total is not None, 0.15), total_ev),
    }

    return fields


def extracted_fields_to_json(fields: dict[str, ExtractedField]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in fields.items():
        out[k] = {
            "value": v.value,
            "confidence": round(float(v.confidence), 4),
            "evidence": v.evidence,
        }
    return out
