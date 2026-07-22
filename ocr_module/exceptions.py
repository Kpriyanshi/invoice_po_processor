class OCRModuleError(Exception):
    """Base class for all errors raised by this module."""


class UnsupportedFileTypeError(OCRModuleError):
    """Raised when the input file is not an image or PDF."""


class VisionAPIError(OCRModuleError):
    """Raised when the OpenAI API call fails after all retries."""


class LowConfidenceError(OCRModuleError):
    """
    Raised (optionally) when overall_confidence falls below the caller's
    threshold. Callers that want to route low-confidence documents to a
    human review queue instead of raising can pass raise_on_low_confidence=False.
    """
