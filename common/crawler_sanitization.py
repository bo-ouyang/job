"""Shared text redaction for crawler logs, telemetry, and persisted events."""

import re


SENSITIVE_TEXT_PATTERNS = (
    re.compile(
        r"(?i)(cookie\s*[:=]\s*)(.*?)(?=\s+(?:authorization|password|token|proxy|(?:request|response)\s*(?:body|text|content)|body)\s*[:=]|$)"
    ),
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)([^\s,;]+)"),
    # A standalone HTTP Authorization scheme has no field-name prefix.
    re.compile(r"(\bBearer\s+)([^\s,;]+)"),
    re.compile(r"(?i)((?:password|token|proxy|secret|credential)\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)((?:request|response)\s*(?:body|text|content)\s*[:=]\s*)(.*)$"),
    re.compile(r"(?i)(\bbody\s*[:=]\s*)(.*)$"),
)


def redact_crawler_text(value, *, max_length: int) -> str:
    text = str(value)[:max_length]
    for pattern in SENSITIVE_TEXT_PATTERNS:
        text = pattern.sub(lambda match: match.group(1) + "[REDACTED]", text)
    return text
