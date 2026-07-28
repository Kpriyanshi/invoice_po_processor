"""
Live GSTIN verification via gstincheck.co.in.

GET {base}/check/{api_key}/{gstin}
Docs: https://gstincheck.co.in/
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from ocr_module.gstin_validation import validate_gstin

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = {"active", "valid", "registered"}


@dataclass(frozen=True)
class GstinApiCheckResult:
    party: str  # "vendor" | "buyer"
    gstin: str | None
    ok: bool
    reason: str


def _normalize_status(value: object) -> str:
    return str(value or "").strip().lower()


def _status_from_payload(data: dict) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in (
        "gstin_status",
        "status",
        "taxpayer_status",
        "registration_status",
        "sts",
    ):
        if key in data and data[key] is not None:
            return _normalize_status(data[key])
    nested = data.get("data")
    if isinstance(nested, dict):
        return _status_from_payload(nested)
    return None


def verify_gstin_via_api(gstin: str) -> GstinApiCheckResult:
    """
    Verify a single GSTIN with local checksum first, then gstincheck API.
    party is left empty for single-gstin calls; callers set party.
    """
    local = validate_gstin(gstin)
    if not local.is_valid:
        return GstinApiCheckResult(
            party="",
            gstin=local.normalized or gstin,
            ok=False,
            reason=f"local format invalid: {local.reason}",
        )

    normalized = local.normalized or gstin
    settings = get_settings()
    if not settings.gstin_api_key:
        return GstinApiCheckResult(
            party="",
            gstin=normalized,
            ok=False,
            reason="GSTIN_API_KEY not configured",
        )

    base = settings.gstin_api_base_url.rstrip("/")
    url = f"{base}/check/{settings.gstin_api_key}/{normalized}"
    try:
        with httpx.Client(timeout=settings.gstin_api_timeout_sec) as client:
            response = client.get(url)
    except httpx.HTTPError as e:
        return GstinApiCheckResult(
            party="",
            gstin=normalized,
            ok=False,
            reason=f"gstin API request failed: {e}",
        )

    try:
        payload = response.json()
    except ValueError:
        return GstinApiCheckResult(
            party="",
            gstin=normalized,
            ok=False,
            reason=f"gstin API non-JSON response (HTTP {response.status_code})",
        )

    if not isinstance(payload, dict):
        return GstinApiCheckResult(
            party="",
            gstin=normalized,
            ok=False,
            reason="gstin API returned unexpected payload",
        )

    if response.status_code >= 400:
        msg = payload.get("message") or payload.get("errorCode") or response.text[:200]
        return GstinApiCheckResult(
            party="",
            gstin=normalized,
            ok=False,
            reason=f"gstin API HTTP {response.status_code}: {msg}",
        )

    if payload.get("flag") is False:
        msg = payload.get("message") or payload.get("errorCode") or "flag=false"
        return GstinApiCheckResult(
            party="",
            gstin=normalized,
            ok=False,
            reason=f"gstin API rejected: {msg}",
        )

    # Some responses use flag=true; others only return data on success.
    status = _status_from_payload(payload)
    if status and status not in _ACTIVE_STATUSES and status not in {"", "none", "null"}:
        # Cancelled / suspended / inactive → reject
        if status in {"cancelled", "canceled", "suspended", "inactive", "invalid"}:
            return GstinApiCheckResult(
                party="",
                gstin=normalized,
                ok=False,
                reason=f"gstin status not active: {status}",
            )

    if payload.get("flag") is True or status in _ACTIVE_STATUSES or payload.get("data"):
        return GstinApiCheckResult(
            party="",
            gstin=normalized,
            ok=True,
            reason="valid via gstin API",
        )

    msg = payload.get("message") or "unable to confirm GSTIN"
    return GstinApiCheckResult(
        party="",
        gstin=normalized,
        ok=False,
        reason=f"gstin API inconclusive: {msg}",
    )


def _check_party(party: str, gstin: str | None, *, required: bool) -> GstinApiCheckResult | None:
    """
    Returns a failed GstinApiCheckResult when rejected, None when OK / skipped.
    """
    value = (gstin or "").strip()
    if not value:
        if required:
            return GstinApiCheckResult(
                party=party,
                gstin=None,
                ok=False,
                reason=f"{party}_gstin missing — rejected for manual review",
            )
        logger.info("GSTIN check skipped — %s_gstin not present on invoice", party)
        return None

    # Strip common OCR noise (spaces)
    value = re.sub(r"\s+", "", value)
    result = verify_gstin_via_api(value)
    if result.ok:
        logger.info("GSTIN API OK | party=%s gstin=%s", party, result.gstin)
        return None

    return GstinApiCheckResult(
        party=party,
        gstin=result.gstin,
        ok=False,
        reason=f"{party}_gstin invalid: {result.reason}",
    )


def validate_party_gstins(
    vendor_gstin: str | None,
    buyer_gstin: str | None,
) -> list[GstinApiCheckResult]:
    """
    Validate seller (required) and buyer (if present) GSTINs.
    Returns list of failed checks (empty means pass).
    """
    settings = get_settings()
    if not settings.gstin_api_validation_enabled:
        logger.info("GSTIN API validation disabled")
        return []

    if not settings.gstin_api_key:
        logger.warning(
            "GSTIN API validation enabled but GSTIN_API_KEY is empty — skipping"
        )
        return []

    failures: list[GstinApiCheckResult] = []
    vendor_fail = _check_party("vendor", vendor_gstin, required=True)
    if vendor_fail is not None:
        failures.append(vendor_fail)

    buyer_fail = _check_party("buyer", buyer_gstin, required=False)
    if buyer_fail is not None:
        failures.append(buyer_fail)

    return failures
