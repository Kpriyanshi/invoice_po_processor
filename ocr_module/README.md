# GPT-4 Vision OCR module

A standalone, drop-in replacement for the EasyOCR + Tesseract + Pydantic-mapping
step in Phase 2 (Document Processing & OCR) of the invoice/PO pipeline. Instead
of raw-text OCR followed by separate NLP field extraction, it sends page images
straight to GPT-4o and gets structured, typed fields back in one call.

## Why a separate module now

This is built to be integrated later without changing Phase 3/4, which already
expect a structured invoice object. The output type, `InvoiceExtraction`, is a
Pydantic model with the same shape (vendor, GSTIN, PO number, line items,
totals) that those phases consume today — so integration is swapping the
function that produces that object, not changing anything downstream.

## Install

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in OCR_OPENAI_API_KEY
```

## Usage

```python
from ocr_module import GPT4VisionOCR

ocr = GPT4VisionOCR()
result = await ocr.extract("invoice_0001.pdf")

result.data                 # InvoiceExtraction — the structured fields
result.overall_confidence   # 0-1, from confidence.py
result.warnings             # human-readable list of anything suspicious
```

Multi-page PDFs are handled automatically — every page is sent to the model in
one request so it can merge line items across pages.

## Design notes

- **Structured Outputs, not prompt-and-hope-for-JSON.** Uses OpenAI's
  `chat.completions.parse` with `response_format=InvoiceExtraction`, which
  constrains generation to match the schema exactly (see `schemas.py`).
- **Confidence scoring is independent of the model.** `confidence.py` doesn't
  ask GPT-4o how confident it is (LLMs self-report confidence poorly). Instead
  it checks completeness of required fields, GSTIN format, and arithmetic
  consistency (subtotal + tax = total, line items sum to subtotal) — the same
  spirit as the original OCR-confidence layer, applied to structured data
  instead of character-level OCR confidence.
- **`fields_model_could_not_read`** lets the model flag fields it saw but
  couldn't read confidently (smudge, fold, glare) versus fields that were
  genuinely absent from the document — the confidence scorer treats these
  differently.
- **Pinned model snapshot** (`gpt-4o-2024-08-06` by default, in `config.py`)
  rather than a floating alias, so extraction behavior doesn't drift under you
  when OpenAI updates the default. Bump deliberately after testing.
- **Images are downscaled** to `OCR_MAX_IMAGE_DIMENSION` (default 2000px) and
  PDFs rendered at `OCR_PDF_RENDER_DPI` (default 200) via PyMuPDF — the same
  PDF library already used elsewhere in the pipeline for PO parsing, so this
  doesn't add a second PDF dependency.

## Files

| File              | Purpose                                              |
|-------------------|-------------------------------------------------------|
| `schemas.py`      | `InvoiceExtraction`, `LineItem`, `OCRExtractionResult` |
| `vision_ocr.py`   | `GPT4VisionOCR` — the main entry point                 |
| `preprocessing.py`| PDF→image rendering, resizing, base64 encoding         |
| `confidence.py`   | Independent confidence/consistency scoring             |
| `config.py`       | `OCRSettings` (env-var driven)                         |
| `exceptions.py`   | `VisionAPIError`, `LowConfidenceError`, etc.           |
| `example_usage.py`| Standalone CLI smoke test                              |

## Known limitations (carried over from GPT-4o vision generally)

- Non-Latin scripts, small/rotated text, and heavily degraded scans are
  weaker points — if your invoices are in scripts other than Latin, validate
  accuracy on a sample before switching over from EasyOCR (which handles
  mixed scripts well).
- Cost/latency per document is higher than local OCR — worth checking against
  your volume before running this on 100% of traffic. A common middle ground
  is to route only low-EasyOCR-confidence documents here.

## Integrating later ("the first part")

When you're ready to wire this into the main pipeline:
1. Point Phase 2's document-processing step at `GPT4VisionOCR.extract()`
   instead of (or as a fallback alongside) the EasyOCR/Tesseract call.
2. `result.data` is already the Pydantic object Phase 3's validators expect —
   no reshaping needed.
3. Decide on a confidence policy: either pass `raise_on_low_confidence=True`
   and catch `LowConfidenceError` to route to human review, or just persist
   `result.overall_confidence` alongside the record and filter downstream.
