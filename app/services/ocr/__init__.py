"""
OCR package for this app.

PRODUCTION path (mail ingest + manual jobs):
  app.services.ocr.vision_service.run_vision_ocr_job
  → ocr_module.GPT4VisionOCR (GPT-4o vision)

LEGACY (do not use for ingest):
  app.services.ocr.pipeline / ocr_engine / extractor  (EasyOCR)
"""

from app.services.ocr.vision_service import OcrJob, run_vision_ocr_job

__all__ = ["OcrJob", "run_vision_ocr_job"]
