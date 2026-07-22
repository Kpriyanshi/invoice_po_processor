from __future__ import annotations

import cv2
import numpy as np


def _unsharp(gray: np.ndarray, amount: float = 1.2, sigma: float = 1.0) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (0, 0), sigma)
    sharp = cv2.addWeighted(gray, 1.0 + amount, blurred, -amount, 0)
    return np.clip(sharp, 0, 255).astype(np.uint8)


def _deskew(gray: np.ndarray, max_angle: float = 5.0) -> np.ndarray:
    try:
        thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thr > 0))
        if coords.size < 100:
            return gray
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if abs(angle) < 0.5 or abs(angle) > max_angle:
            return gray
        h, w = gray.shape[:2]
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        return cv2.warpAffine(
            gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )
    except Exception:
        return gray


def preprocess_for_ocr(
    image_bgr: np.ndarray,
    upscale: float | None = None,
    target_side: int = 1600,
) -> np.ndarray:
    """
    Grayscale + light deskew + adaptive upscale/cap to target_side + unsharp.
    No full-page CLAHE/Otsu (was washing text and blowing RAM with 1.5x).
    """
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("Empty image")

    if len(image_bgr.shape) == 2:
        gray = image_bgr.copy()
    else:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    gray = _deskew(gray)

    h, w = gray.shape[:2]
    long_side = max(h, w)

    if upscale is not None and upscale != 1.0:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    elif target_side and long_side < target_side:
        scale = target_side / float(long_side)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    elif target_side and long_side > target_side:
        scale = target_side / float(long_side)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    return _unsharp(gray)


def to_rgb_for_easyocr(image_gray_or_bgr: np.ndarray) -> np.ndarray:
    if len(image_gray_or_bgr.shape) == 2:
        return cv2.cvtColor(image_gray_or_bgr, cv2.COLOR_GRAY2RGB)
    return cv2.cvtColor(image_gray_or_bgr, cv2.COLOR_BGR2RGB)


def crop_bbox_rgb(page_rgb: np.ndarray, bbox: list, pad: float = 0.08) -> np.ndarray | None:
    try:
        pts = np.array(bbox, dtype=np.float32)
        x_min, x_max = int(pts[:, 0].min()), int(pts[:, 0].max())
        y_min, y_max = int(pts[:, 1].min()), int(pts[:, 1].max())
    except Exception:
        return None
    h, w = page_rgb.shape[:2]
    bw, bh = max(1, x_max - x_min), max(1, y_max - y_min)
    pad_x, pad_y = int(bw * pad), int(bh * pad)
    x0, y0 = max(0, x_min - pad_x), max(0, y_min - pad_y)
    x1, y1 = min(w, x_max + pad_x), min(h, y_max + pad_y)
    if x1 <= x0 or y1 <= y0:
        return None
    return page_rgb[y0:y1, x0:x1].copy()
