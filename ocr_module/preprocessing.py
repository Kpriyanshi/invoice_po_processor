"""
Turns an input file (image or PDF) into a list of base64-encoded PNG pages
ready to send to the vision API.

Uses PyMuPDF for PDF rendering, matching the library already used elsewhere
in the pipeline (Phase 2 and Phase 4 PO parsing), so no new PDF dependency
is introduced.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from .config import OCRSettings
from .exceptions import UnsupportedFileTypeError

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
PDF_EXTENSIONS = {".pdf"}


def _resize_if_needed(img: Image.Image, max_dimension: int) -> Image.Image:
    longest_side = max(img.size)
    if longest_side <= max_dimension:
        return img
    scale = max_dimension / longest_side
    new_size = (int(img.width * scale), int(img.height * scale))
    return img.resize(new_size, Image.LANCZOS)


def _image_to_base64_png(img: Image.Image) -> str:
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def load_pages_as_base64(file_path: str, settings: OCRSettings) -> list[str]:
    """
    Returns a list of base64-encoded PNG strings, one per page.
    A plain image file yields a single-element list.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix in IMAGE_EXTENSIONS:
        with Image.open(path) as img:
            img.load()
            img = _resize_if_needed(img, settings.max_image_dimension)
            return [_image_to_base64_png(img)]

    if suffix in PDF_EXTENSIONS:
        pages: list[str] = []
        doc = fitz.open(path)
        try:
            zoom = settings.pdf_render_dpi / 72  # PDF base unit is 72 DPI
            matrix = fitz.Matrix(zoom, zoom)
            for page in doc:
                pix = page.get_pixmap(matrix=matrix)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                img = _resize_if_needed(img, settings.max_image_dimension)
                pages.append(_image_to_base64_png(img))
        finally:
            doc.close()
        return pages

    raise UnsupportedFileTypeError(
        f"'{suffix}' is not supported. Expected one of "
        f"{sorted(IMAGE_EXTENSIONS | PDF_EXTENSIONS)}."
    )
