from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always the monorepo root (parent of this package directory).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ROOT_ENV = _PROJECT_ROOT / ".env"


class OCRSettings(BaseSettings):
    """
    Production OCR settings — single source of truth:

      <project_root>/.env

    Do not put secrets only in ocr_module/.env. That file is legacy for
    standalone experiments; the mail ingest path and GPT4VisionOCR both
    load from the project root .env via this class.
    """

    model_config = SettingsConfigDict(
        env_prefix="OCR_",
        env_file=str(_ROOT_ENV),
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    openai_api_key: str = ""

    # Pinned snapshot rather than a floating alias, so behavior doesn't
    # silently change under you. Bump deliberately after testing.
    model_name: str = "gpt-4o-2024-08-06"

    max_retries: int = 3
    request_timeout_seconds: float = 60.0

    # Images are downscaled to this max longest-side dimension before being
    # sent, to control token cost. GPT-4o's high-detail mode tiles the image;
    # beyond ~2000px you're mostly paying more without extraction quality gains.
    max_image_dimension: int = 2000

    # PDFs are rendered at this DPI before being handed to the model.
    pdf_render_dpi: int = 200

    # Documents with overall_confidence below this are flagged in warnings
    # (and optionally raise LowConfidenceError -- see vision_ocr.py).
    low_confidence_threshold: float = 0.6

    # When True, run a second vision call focused on GSTIN if either is missing.
    gstin_focused_pass: bool = True

    @staticmethod
    def project_root() -> Path:
        return _PROJECT_ROOT

    @staticmethod
    def env_file_path() -> Path:
        return _ROOT_ENV
