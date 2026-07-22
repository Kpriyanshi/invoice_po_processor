from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List

import cv2
import numpy as np

import easyocr


@dataclass
class OcrLine:
    text: str
    confidence: float
    bbox: list
    page_index: int


@lru_cache(maxsize=1)
def get_reader(langs_csv: str = "en") -> easyocr.Reader:
    langs = [s.strip() for s in langs_csv.split(",") if s.strip()]
    return easyocr.Reader(langs, gpu=False)


def _cap_side(rgb: np.ndarray, max_side: int) -> np.ndarray:
    h, w = rgb.shape[:2]
    m = max(h, w)
    if max_side <= 0 or m <= max_side:
        return rgb
    scale = max_side / float(m)
    return cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def run_easyocr(
    page_rgb: np.ndarray,
    page_index: int,
    langs_csv: str = "en",
    allowlist: str | None = None,
    canvas_size: int = 1280,
    mag_ratio: float = 1.0,
    max_side: int = 1600,
) -> List[OcrLine]:
    """
    EasyOCR with memory-safe canvas / image caps (prevents ~1.2GB CPU alloc crashes).
    """
    reader = get_reader(langs_csv)
    img = _cap_side(page_rgb, max_side)
    kwargs: dict = {
        "decoder": "beamsearch",
        "beamWidth": 5,
        "paragraph": False,
        "canvas_size": canvas_size,
        "mag_ratio": mag_ratio,
    }
    if allowlist:
        kwargs["allowlist"] = allowlist

    results = reader.readtext(img, **kwargs)

    lines: List[OcrLine] = []
    for bbox, text, conf in results:
        cleaned = " ".join(str(text).split())
        if not cleaned:
            continue
        lines.append(
            OcrLine(
                text=cleaned,
                confidence=float(conf),
                bbox=bbox,
                page_index=page_index,
            )
        )
    return lines


ALLOWLIST_GSTIN = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ALLOWLIST_AMOUNT = "0123456789.,"
ALLOWLIST_DATE = "0123456789/-."
ALLOWLIST_ID = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-/"
