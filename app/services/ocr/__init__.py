"""
OCR package for this app.

Production path (mail ingest + manual jobs):
  app.services.ocr.vision_service.run_vision_ocr_job
  → ocr_module.GPT4VisionOCR (GPT-4o vision)
"""

from app.services.ocr.vision_service import OcrJob, run_vision_ocr_job

__all__ = ["OcrJob", "run_vision_ocr_job"]
