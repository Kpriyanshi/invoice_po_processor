from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    gmail_token_path: str = 'data/token.json'
    gmail_credentials_path: str = 'credentials.json'
    confidence_threshold: int = 60
    invoice_save_folder: str = 'data/invoices'
    processed_ids_path: str = 'data/processed_ids.json'
    last_history_id_path: str = 'data/last_history_id.json'
    exception_queue_path: str = 'data/exception_queue.json'
    pubsub_topic: str = 'projects/invoice-and-po-processing/topics/invoice'
    host: str = '0.0.0.0'
    port: int = 8000
    log_level: str = 'INFO'

    # Security — MIME validation
    mime_validation_enabled: bool = True
    max_attachment_size_mb: int = 25
    allowed_mime_types: str = (
        'application/pdf,'
        'application/msword,'
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document,'
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,'
        'application/zip'
    )
    quarantine_path: str = 'data/quarantine.json'

    # Security — ClamAV malware scanning
    malware_scan_enabled: bool = True
    clamav_host: str = 'localhost'
    clamav_port: int = 3310
    clamav_scan_timeout_sec: int = 30
    malware_scan_fail_open: bool = False

    # OCR — GPT-4 Vision on ingest (EasyOCR settings kept for legacy scripts)
    ocr_enabled: bool = True
    ocr_dpi: int = 150
    max_pages_per_pdf: int = 10
    ocr_languages: str = 'en'
    ocr_output_dir: str = 'data/extracted'
    ocr_debug_images: bool = False
    ocr_debug_dir: str = 'data/debug'

    def allowed_mime_set(self) -> set[str]:
        return {m.strip() for m in self.allowed_mime_types.split(',') if m.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
