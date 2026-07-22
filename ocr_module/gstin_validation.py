"""
Rule-based GSTIN validation (structure + mod-36 checksum).

GSTIN layout (15 alphanumeric):
  1-2   State / UT code
  3-12  PAN (5 letters + 4 digits + 1 letter)
  13    Entity / registration number for that PAN in the state
  14    Literal 'Z'
  15    Check character (Luhn mod-36 over the first 14 characters)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Official GST state / UT codes (01–38; gaps are unused)
_VALID_STATE_CODES = {
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "10",
    "11",
    "12",
    "13",
    "14",
    "15",
    "16",
    "17",
    "18",
    "19",
    "20",
    "21",
    "22",
    "23",
    "24",
    "26",
    "27",
    "29",
    "30",
    "31",
    "32",
    "33",
    "34",
    "35",
    "36",
    "37",
    "38",
}

_PAN_SEGMENT_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_ENTITY_CHAR_RE = re.compile(r"^[1-9A-Z]$")

_GSTIN_SEARCH = re.compile(
    r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GstinValidationResult:
    is_valid: bool
    normalized: str | None
    reason: str


def _checksum_valid(gstin_upper: str) -> bool:
    if len(gstin_upper) != 15:
        return False
    factor = 1
    total = 0
    mod = len(_CHARSET)
    for ch in gstin_upper[:14]:
        code_point = _CHARSET.find(ch)
        if code_point < 0:
            return False
        weighted = factor * code_point
        weighted = (weighted // mod) + (weighted % mod)
        total += weighted
        factor = 2 if factor == 1 else 1
    expected = _CHARSET[(mod - (total % mod)) % mod]
    return expected == gstin_upper[14]


def validate_gstin(gstin: str | None) -> GstinValidationResult:
    if not gstin or not str(gstin).strip():
        return GstinValidationResult(False, None, "missing")

    normalized = re.sub(r"\s+", "", str(gstin).strip().upper())
    if len(normalized) != 15:
        return GstinValidationResult(False, normalized, "must be 15 characters")

    if not normalized.isalnum():
        return GstinValidationResult(False, normalized, "must be alphanumeric")

    state_code = normalized[:2]
    if not state_code.isdigit():
        return GstinValidationResult(False, normalized, "invalid state code format")
    if state_code not in _VALID_STATE_CODES:
        return GstinValidationResult(False, normalized, f"unknown state code {state_code}")

    pan_segment = normalized[2:12]
    if not _PAN_SEGMENT_RE.match(pan_segment):
        return GstinValidationResult(False, normalized, "invalid PAN segment (chars 3–12)")

    entity_char = normalized[12]
    if not _ENTITY_CHAR_RE.match(entity_char):
        return GstinValidationResult(False, normalized, "invalid entity number (13th character)")

    if normalized[13] != "Z":
        return GstinValidationResult(False, normalized, "14th character must be Z")

    if not _checksum_valid(normalized):
        return GstinValidationResult(False, normalized, "checksum failed")

    return GstinValidationResult(True, normalized, "valid")


def find_valid_gstin_in_text(text: str | None) -> str | None:
    """Return the first checksum-valid GSTIN found in free text."""
    if not text:
        return None
    compact = text.replace(" ", "").upper()
    for match in _GSTIN_SEARCH.finditer(compact):
        candidate = match.group(0).upper()
        result = validate_gstin(candidate)
        if result.is_valid:
            return result.normalized
    for match in _GSTIN_SEARCH.finditer(text.upper()):
        candidate = match.group(0).upper()
        result = validate_gstin(candidate)
        if result.is_valid:
            return result.normalized
    return None


def _confusable_alternatives(char: str) -> set[str]:
    groups = (
        set("0O"),
        set("1IL"),
        set("5S"),
        set("8B"),
        set("CG"),
        set("KHX"),
        set("MN"),
        set("UV"),
        set("2Z"),
    )
    alts: set[str] = set()
    upper = char.upper()
    for group in groups:
        if upper in group:
            alts |= group
    alts.discard(upper)
    return alts


def _repair_score(original: str, repaired: str) -> tuple[int, int, int]:
    """Lower is better: (changes outside PAN, changes inside PAN, levenshtein)."""
    outside_pan = sum(
        1 for i in range(15) if i not in range(2, 12) and original[i] != repaired[i]
    )
    inside_pan = sum(1 for i in range(2, 12) if original[i] != repaired[i])
    # Simple Levenshtein
    if len(original) != len(repaired):
        lev = 99
    else:
        lev = sum(1 for a, b in zip(original, repaired) if a != b)
    return (outside_pan, inside_pan, lev)


def repair_gstin_candidates(gstin: str | None) -> list[str]:
    """
    Generate checksum-valid GSTIN candidates from a near-miss OCR reading
    using adjacent transpositions and common character confusions.
    """
    if not gstin or not str(gstin).strip():
        return []

    original = re.sub(r"\s+", "", str(gstin).strip().upper())
    if len(original) != 15:
        return []

    found: list[str] = []

    def add(candidate: str) -> None:
        result = validate_gstin(candidate)
        if result.is_valid and result.normalized and result.normalized not in found:
            found.append(result.normalized)

    result = validate_gstin(original)
    if result.is_valid and result.normalized:
        return [result.normalized]

    for i in range(len(original) - 1):
        chars = list(original)
        chars[i], chars[i + 1] = chars[i + 1], chars[i]
        add("".join(chars))

    for i in range(len(original)):
        for alt in _confusable_alternatives(original[i]):
            chars = list(original)
            chars[i] = alt
            add("".join(chars))

    found.sort(key=lambda repaired: _repair_score(original, repaired))
    return found


def repair_gstin(gstin: str | None) -> str | None:
    """
    Pick the best repaired GSTIN when OCR produced a structurally similar
    but checksum-invalid value. Returns None when ambiguous.
    """
    candidates = repair_gstin_candidates(gstin)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    original = re.sub(r"\s+", "", str(gstin).strip().upper())
    scored = [( _repair_score(original, c), c) for c in candidates]
    scored.sort(key=lambda item: item[0])
    best_score, best = scored[0]
    second_score, _ = scored[1]

    # Accept a clear winner (PAN-only fix preferred).
    if best_score[0] == 0 and best_score[1] <= 2 and best_score != second_score:
        return best
    if best_score != second_score and best_score[0] == 0:
        return best
    return None


def find_all_valid_gstins_in_text(text: str | None) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for blob in (text.replace(" ", "").upper(), text.upper()):
        for match in _GSTIN_SEARCH.finditer(blob):
            candidate = match.group(0).upper()
            if candidate in seen:
                continue
            seen.add(candidate)
            result = validate_gstin(candidate)
            if result.is_valid and result.normalized:
                ordered.append(result.normalized)
    return ordered
