"""Token usage as reported by the provider. Fields are None where the provider reported nothing; never guessed."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Usage:
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]


def usage_from_message(message) -> Optional[Usage]:
    meta = getattr(message, "usage_metadata", None)
    if not meta:
        return None
    return Usage(meta.get("input_tokens"), meta.get("output_tokens"), meta.get("total_tokens"))
