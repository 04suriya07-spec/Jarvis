"""Secret redaction helpers for logs and audit entries."""

from __future__ import annotations

import re
from typing import Any


_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|app[_-]?password)\s*[:=]\s*['\"]?([^'\"\s,}]+)"),
    re.compile(r"(?i)(bearer\s+)([a-z0-9._\-]{12,})"),
    re.compile(r"(?i)(sk-[a-z0-9_\-]{12,})"),
    re.compile(r"(?i)(ghp_[a-z0-9_]{12,})"),
]


def redact_text(text: str) -> str:
    out = str(text)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            out = pattern.sub(lambda m: f"{m.group(1)}=<redacted>", out)
        else:
            out = pattern.sub("<redacted>", out)
    return out


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if re.search(r"(?i)(api[_-]?key|token|secret|password|app[_-]?password|cookie)", str(key)):
                out[key] = "<redacted>"
            else:
                out[key] = redact_value(val)
        return out
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    return value
