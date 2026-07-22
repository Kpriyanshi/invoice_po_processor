"""
Merge OCR_* keys from ocr_module/.env into the project-root .env.

Production uses ONLY <repo>/.env. This script copies OCR settings once
so you do not maintain two env files.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_ENV = ROOT / ".env"
MODULE_ENV = ROOT / "ocr_module" / ".env"

REQUIRED = {
    "OCR_ENABLED": "true",
    "OCR_OUTPUT_DIR": "data/extracted",
}


def _parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def main() -> int:
    root_vals = _parse(ROOT_ENV)
    mod_vals = _parse(MODULE_ENV)

    # Prefer module values for OCR_* when root is missing them
    merged = dict(root_vals)
    for key, val in mod_vals.items():
        if not key.startswith("OCR_"):
            continue
        if key not in merged or not merged[key]:
            merged[key] = val

    for key, default in REQUIRED.items():
        merged.setdefault(key, default)

    if not merged.get("OCR_OPENAI_API_KEY"):
        print("ERROR: OCR_OPENAI_API_KEY not found in root .env or ocr_module/.env")
        return 1

    # Rewrite root .env: keep non-OCR lines, then write a clean OCR block
    non_ocr: list[str] = []
    if ROOT_ENV.is_file():
        for raw in ROOT_ENV.read_text(encoding="utf-8-sig").splitlines():
            if raw.strip().startswith("OCR_"):
                continue
            non_ocr.append(raw)
    while non_ocr and non_ocr[-1].strip() == "":
        non_ocr.pop()

    ocr_keys = [
        "OCR_ENABLED",
        "OCR_OUTPUT_DIR",
        "OCR_OPENAI_API_KEY",
        "OCR_MODEL_NAME",
        "OCR_MAX_RETRIES",
        "OCR_REQUEST_TIMEOUT_SECONDS",
        "OCR_MAX_IMAGE_DIMENSION",
        "OCR_PDF_RENDER_DPI",
        "OCR_LOW_CONFIDENCE_THRESHOLD",
        "OCR_GSTIN_FOCUSED_PASS",
    ]
    # Keep any other OCR_* (e.g. debug) after the standard block
    extra = sorted(k for k in merged if k.startswith("OCR_") and k not in ocr_keys)

    lines = list(non_ocr)
    lines.append("")
    lines.append("# OCR — GPT-4 Vision (single source of truth for production)")
    for key in ocr_keys + extra:
        if key in merged and merged[key] != "":
            lines.append(f"{key}={merged[key]}")
    lines.append("")

    ROOT_ENV.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote OCR settings to {ROOT_ENV}")
    print(f"API key present: {bool(merged.get('OCR_OPENAI_API_KEY'))}")
    print("Run: .\\venv\\Scripts\\python.exe scripts\\check_ocr_config.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
