print("===== Script Started =====")

from pathlib import Path
import cv2

from app.services.ocr.pdf_loader import iter_pdf_page_images
from app.services.ocr.preprocess import preprocess_for_ocr, to_rgb_for_easyocr
from app.services.ocr.ocr_engine import run_easyocr

PDF_PATH = r"data\invoices\This is a Tax Invoice_invoice.pdf.pdf"

OUTPUT = Path("data/debug/dpi_test")
OUTPUT.mkdir(parents=True, exist_ok=True)

DPIS = [100, 150, 200, 250, 300]

print("=" * 80)
print("DPI OCR BENCHMARK")
print("=" * 80)

for dpi in DPIS:

    print(f"\nTesting DPI = {dpi}")

    for page in iter_pdf_page_images(PDF_PATH, dpi=dpi, max_pages=1):

        print(f"Image size : {page.width} x {page.height}")

        cv2.imwrite(
            str(OUTPUT / f"page_{dpi}.png"),
            page.image_bgr
        )

        processed = preprocess_for_ocr(page.image_bgr)

        rgb = to_rgb_for_easyocr(processed)

        lines = run_easyocr(
            rgb,
            page_index=0,
            langs_csv="en"
        )

        text = "\n".join(l.text for l in lines)

        confidence = (
            sum(l.confidence for l in lines) / len(lines)
            if lines else 0
        )

        print(f"Characters : {len(text)}")
        print(f"Words      : {len(text.split())}")
        print(f"Lines      : {len(lines)}")
        print(f"Confidence : {confidence:.3f}")

        with open(
            OUTPUT / f"ocr_{dpi}.txt",
            "w",
            encoding="utf-8"
        ) as f:
            f.write(text)
print("\nDone.")
