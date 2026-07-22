"""Validate production OCR config (project-root .env only)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from app.core.config import get_settings
    from ocr_module import OCRSettings

    app = get_settings()
    ocr = OCRSettings()
    env_path = OCRSettings.env_file_path()

    print("Production OCR config check")
    print(f"  project_root     : {OCRSettings.project_root()}")
    print(f"  env_file         : {env_path}  exists={env_path.is_file()}")
    print(f"  OCR_ENABLED      : {app.ocr_enabled}")
    print(f"  OCR_OUTPUT_DIR   : {app.ocr_output_dir}")
    print(f"  OCR_MODEL_NAME   : {ocr.model_name}")
    print(f"  API key loaded   : {bool(ocr.openai_api_key)}")

    if not env_path.is_file():
        print("FAIL: project-root .env is missing")
        return 1
    if not app.ocr_enabled:
        print("FAIL: OCR_ENABLED is false")
        return 1
    if not ocr.openai_api_key:
        print(
            "FAIL: OCR_OPENAI_API_KEY not loaded from project-root .env "
            "(ignore ocr_module/.env — that is not used in production)"
        )
        return 1

    print("OK: GPT Vision OCR is configured for mail ingest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
