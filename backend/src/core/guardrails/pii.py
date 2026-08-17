"""PII redaction via Presidio (BLUEPRINT.md §3.12, OWASP LLM02).

Presidio (MIT, independently governed as of mid-2026) is an OPTIONAL
dependency -- `presidio-analyzer`/`presidio-anonymizer` are NOT in this
backend's base `dependencies`, only its `guardrails` dependency group
(`pyproject.toml`) -- offline-first, design principle #4: this template
boots and its test suite runs with zero guardrail credentials or model
downloads. Install the group (`uv sync --group guardrails`) before setting
`GUARDRAILS_ENABLED=true` in any environment that needs real PII
redaction.

`redact_pii` degrades to a loud no-op (returns the text unchanged, logs at
error level) rather than crashing a turn if Presidio isn't installed or its
analysis itself fails -- guardrails are one defense-in-depth layer among
several here, not the only one (§3.12: "the structlog censor is logs-only
and is not data protection -- say so loudly" applies just as much to a
missing optional dependency silently doing nothing).
"""

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
                "aren't installed -- run `uv sync --group guardrails` (BLUEPRINT.md §3.12). "
                "PII redaction is being skipped until then.",
            )
            _warned_missing = True
        return None
    _engines = (AnalyzerEngine(), AnonymizerEngine())
    return _engines


def redact_pii(text: str) -> str:
    """Best-effort PII redaction -- returns `text` unchanged if Presidio
    isn't installed, or its analysis finds nothing to redact."""
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
