"""Export one LangSmith trace as nested JSON (FR-8). The trace ID is shown in Developer mode and by scripts/ask.py.

    python scripts/export_trace.py <trace-id>                          # print the JSON
    python scripts/export_trace.py <trace-id> --out docs/traces/example-trace.json
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from iqm_rag import config
from iqm_rag.observability.export import fetch_trace, to_json


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace_id", help="the trace (request) ID")
    parser.add_argument("--out", type=Path, default=None, help="write the JSON to this file instead of printing it")
    args = parser.parse_args(argv)
    if not config.langsmith_api_key():
        print("Export stopped: LANGSMITH_API_KEY is not set in .env.", file=sys.stderr)
        return 2
    try:
        text = to_json(fetch_trace(args.trace_id))
    except (LookupError, ValueError) as exc:
        print(f"Export stopped: {exc}", file=sys.stderr)
        return 1
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.out} ({len(text):,} characters)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
