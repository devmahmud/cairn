"""Optional dependency (uv sync --group guardrails) -- degrades to a loud no-op (logs error, text unchanged) rather than crashing a turn if Presidio isn't installed or analysis fails."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_PII_ENTITIES = (
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "US_BANK_NUMBER",
    "IBAN_CODE",
    "IP_ADDRESS",
    "PERSON",
    "LOCATION",
    "CRYPTO",
)

_engines: tuple[Any, Any] | None = None
_warned_missing = False


def _load_engines() -> tuple[Any, Any] | None:
    global _engines, _warned_missing
    if _engines is not None:
        return _engines
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
    except ImportError:
        if not _warned_missing:
            logger.error(
                "guardrails.presidio_not_installed",
                hint="GUARDRAILS_ENABLED=true but presidio-analyzer/presidio-anonymizer "
                "aren't installed -- run `uv sync --group guardrails`. "
                "PII redaction is being skipped until then.",
            )
            _warned_missing = True
        return None
    _engines = (AnalyzerEngine(), AnonymizerEngine())
    return _engines


def redact_pii(text: str) -> str:
    if not text:
        return text
    engines = _load_engines()
    if engines is None:
        return text
    analyzer, anonymizer = engines
    try:
        results = analyzer.analyze(text=text, entities=list(_PII_ENTITIES), language="en")
        if not results:
            return text
        return str(anonymizer.anonymize(text=text, analyzer_results=results).text)
    except Exception:
        logger.exception("guardrails.presidio_analysis_failed")
        return text
