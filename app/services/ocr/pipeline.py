from __future__ import annotations

import json
import os
import time
from typing import Any

from app.core.config import get_settings
from app.services.ocr.extractor import (
    extract_invoice_fields,
    extract_line_items,
    extracted_fields_to_json,
)
from app.services.ocr.ocr_engine import run_easyocr
from app.services.ocr.pdf_loader import iter_pdf_page_images
from app.services.ocr.preprocess import preprocess_for_ocr, to_rgb_for_easyocr


def process_pdf(pdf_path: str) -> dict[str, Any]:
    """
    Run: PDF -> page images -> preprocess -> OCR -> extract fields.
    Returns JSON-like dict.
    """
    settings = get_settings()
    dpi = getattr(settings, "ocr_dpi", 250)
    max_pages = getattr(settings, "max_pages_per_pdf", 10)
    langs = getattr(settings, "ocr_languages", "en")

    started = time.time()

    all_lines = []
    all_confs: list[float] = []
    page_count = 0

    for page in iter_pdf_page_images(pdf_path, dpi=dpi, max_pages=max_pages):
        page_count += 1
        processed = preprocess_for_ocr(page.image_bgr)
        rgb = to_rgb_for_easyocr(processed)
        lines = run_easyocr(rgb, page_index=page.page_index, langs_csv=langs)

        all_lines.extend(lines)
        all_confs.extend([l.confidence for l in lines])

    raw_text = "\n".join([l.text for l in all_lines])
    avg_conf = (sum(all_confs) / len(all_confs)) if all_confs else 0.0

    extracted = extract_invoice_fields(raw_text=raw_text, line_confs=all_confs)
    line_items = extract_line_items(raw_text=raw_text, avg_ocr_conf=avg_conf)

    result = {
        "source_pdf_path": pdf_path,
        "page_count": page_count,
        "raw_text": raw_text,
        "fields": extracted_fields_to_json(extracted),
        "line_items": line_items,
        "ocr_confidence_avg": avg_conf,
        "metadata": {
            "dpi": dpi,
            "max_pages_per_pdf": max_pages,
            "elapsed_ms": int((time.time() - started) * 1000),
        },
    }
    return result


def save_extraction_json(pdf_path: str, output_dir: str | None = None) -> str:
    """
    Writes extraction result JSON into data/extracted/<basename>.json
    Returns output path.
    """
    settings = get_settings()
    out_dir = output_dir or getattr(settings, "ocr_output_dir", "data/extracted")
    os.makedirs(out_dir, exist_ok=True)

    result = process_pdf(pdf_path)

    base = os.path.basename(pdf_path)
    safe = base.replace("\\", "_").replace("/", "_")
    out_path = os.path.join(out_dir, f"{safe}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return out_path