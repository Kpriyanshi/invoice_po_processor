"""Save OCR preprocess step images for one PDF page (debug / inspection)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

# Project root on sys.path when run as script
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import get_settings
from app.services.ocr.pdf_loader import iter_pdf_page_images
from app.services.ocr.preprocess import (
    _deskew,
    _unsharp,
    preprocess_for_ocr,
    to_rgb_for_easyocr,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write preprocess step PNGs for page 0 of a PDF.")
    parser.add_argument(
        "pdf",
        nargs="?",
        default=str(_ROOT / "data" / "invoices" / "This is a Tax Invoice_invoice.pdf.pdf"),
        help="Path to invoice PDF",
    )
    parser.add_argument(
        "-o",
        "--out",
        default=str(_ROOT / "data" / "debug" / "preprocess_steps"),
        help="Output directory for PNGs",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    dpi = settings.ocr_dpi
    target_side = 1600

    page = next(iter_pdf_page_images(str(pdf_path), dpi=dpi, max_pages=1))
    bgr = page.image_bgr

    cv2.imwrite(str(out / "01_original_from_pdf.png"), bgr)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(str(out / "02_grayscale.png"), gray)

    deskewed = _deskew(gray)
    cv2.imwrite(str(out / "03_after_deskew.png"), deskewed)

    h, w = deskewed.shape[:2]
    long_side = max(h, w)
    if long_side < target_side:
        scale = target_side / float(long_side)
        resized = cv2.resize(deskewed, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    elif long_side > target_side:
        scale = target_side / float(long_side)
        resized = cv2.resize(deskewed, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        resized = deskewed.copy()
    cv2.imwrite(str(out / "04_after_resize_to_1600px_long_side.png"), resized)

    sharp = _unsharp(resized)
    cv2.imwrite(str(out / "05_after_unsharp.png"), sharp)

    combined = preprocess_for_ocr(bgr)
    cv2.imwrite(str(out / "06_preprocess_for_ocr_all_in_one.png"), combined)

    rgb = to_rgb_for_easyocr(sharp)
    cv2.imwrite(str(out / "07_rgb_for_easyocr.png"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))

    print("Saved to:", out.resolve())
    for p in sorted(out.glob("*.png")):
        print(" ", p.name)


if __name__ == "__main__":
    main()
