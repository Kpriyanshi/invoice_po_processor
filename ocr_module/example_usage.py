"""
Standalone smoke test / usage example.

Production config is the PROJECT ROOT .env (not ocr_module/.env).

Run from repo root:
    .\\venv\\Scripts\\python.exe ocr_module\\example_usage.py path\\to\\invoice.pdf
"""

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ocr_module import GPT4VisionOCR, LowConfidenceError, OCRSettings


async def main(file_path: str) -> None:
    settings = OCRSettings()
    if not settings.openai_api_key:
        print(
            f"OCR_OPENAI_API_KEY missing in {OCRSettings.env_file_path()}. "
            "Run: python scripts/sync_ocr_env.py"
        )
        sys.exit(1)

    ocr = GPT4VisionOCR(settings)

    try:
        result = await ocr.extract(file_path, raise_on_low_confidence=False)
    except LowConfidenceError as exc:
        print(f"Document needs human review: {exc}")
        return

    print(f"Document type:      {result.data.document_type}")
    print(f"Document label:     {result.data.document_label}")
    print(f"Invoice number:     {result.data.invoice_number}")
    print(f"Invoice date:       {result.data.invoice_date}")
    print(f"Order date:         {result.data.order_date}")
    print(f"Vendor:             {result.data.vendor_name}")
    print(f"Vendor GSTIN:       {result.data.vendor_gstin}")
    print(f"Buyer GSTIN:        {result.data.buyer_gstin}")
    print(f"Supply type:        {result.data.supply_type}")
    print(f"Taxable/Subtotal:   {result.data.subtotal}")
    print(f"CGST amount:        {result.data.cgst_amount} ({result.data.cgst_percent}%)")
    print(f"SGST amount:        {result.data.sgst_amount} ({result.data.sgst_percent}%)")
    print(f"IGST amount:        {result.data.igst_amount} ({result.data.igst_percent}%)")
    print(f"Tax total:          {result.data.tax_amount}")
    print(f"Total:              {result.data.total_amount} {result.data.currency}")
    print(f"Line items:         {len(result.data.line_items)}")
    print(f"Overall confidence: {result.overall_confidence}")

    if result.warnings:
        print("\nWarnings:")
        for w in result.warnings:
            print(f"  - {w}")

    if result.data.line_items:
        print("\nLine items:")
        for i, item in enumerate(result.data.line_items, 1):
            print(
                f"  {i}. {item.description} | qty={item.quantity} | "
                f"unit_price={item.unit_price} | total={item.line_total}"
            )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python example_usage.py <invoice.pdf>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
