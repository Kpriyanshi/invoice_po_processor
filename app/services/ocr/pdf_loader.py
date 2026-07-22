from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import fitz  # PyMuPDF
import numpy as np


@dataclass
class PdfPageImage:
    page_index: int
    image_bgr: np.ndarray  # OpenCV-friendly (BGR)
    width: int
    height: int
    dpi: int


def _pixmap_to_bgr(pix: fitz.Pixmap) -> np.ndarray:
    """
    Convert a PyMuPDF Pixmap to OpenCV BGR uint8 ndarray.
    """
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)  # drop alpha

    # pix.samples is bytes, shape is (h, w, n)
    n = pix.n  # number of channels (3 for RGB)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, n)

    # Convert RGB -> BGR for OpenCV
    if n == 3:
        img = img[:, :, ::-1]
    return img


def iter_pdf_page_images(pdf_path: str, dpi: int = 250, max_pages: int | None = None) -> Iterator[PdfPageImage]:
    doc = fitz.open(pdf_path)
    try:
        page_count = doc.page_count
        limit = page_count if max_pages is None else min(page_count, max_pages)

        for i in range(limit):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=dpi)
            bgr = _pixmap_to_bgr(pix)
            yield PdfPageImage(
                page_index=i,
                image_bgr=bgr,
                width=pix.w,
                height=pix.h,
                dpi=dpi,
            )
    finally:
        doc.close()