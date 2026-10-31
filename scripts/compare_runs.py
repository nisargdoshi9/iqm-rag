"""Print a comparison table of saved evaluation runs, one row per run (FR-9). Reads files only; makes no model calls.

    python scripts/compare_runs.py data/evaluation/results/<run-id> data/evaluation/results/<run-id> ...
    python scripts/compare_runs.py --split holdout          # every completed run of that split, oldest first
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from iqm_rag.evaluation import runner

COLUMNS = ("Configuration", "Recall@1", "Recall@3", "Recall@8", "MRR", "In context", "Right response", "End-to-end", "Facts covered",
           "Claims supported", "No wrong citation", "Citation precision", "Median s", "Cost/question")


def _ratio(value: dict) -> str:
    return f"{value['count']}/{value['of']}"


def row(run_dir: Path) -> dict:
    setup = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["summary"]
    ret, gen, cit, ops = summary["retrieval"], summary["generation"], summary["citation"], summary["operational"]
    label = (setup.get("retrieval") or {}).get("label", runner.LEGACY_RETRIEVAL_LABEL)
    return {"Configuration": label, "Recall@1": _ratio(ret["recall@1"]), "Recall@3": _ratio(ret["recall@3"]), "Recall@8": _ratio(ret["recall@8"]),
            "MRR": ret["mrr"], "In context": _ratio(ret["in_context"]) if "in_context" in ret else "n/a",
            "Right response": _ratio(summary["abstention"]["passed"]), "End-to-end": _ratio(gen["end_to_end_correct"]),
            "Facts covered": _ratio(gen["all_facts_covered"]), "Claims supported": _ratio(gen["faithful"]),
            "No wrong citation": _ratio(cit["no_wrong_citation"]), "Citation precision": cit["mean_precision"],
            "Median s": ops["wall_s"]["median"], "Cost/question": f"${ops['estimated_cost_per_question_usd']}"}


def table(run_dirs: list[Path]) -> str:
    rows = [row(path) for path in run_dirs]
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(str(r[c]) for c in COLUMNS) + " |" for r in rows]
    return "\n".join(lines)


def runs_of_split(results_dir: Path, split: str) -> list[Path]:
    found = []
    for config_file in sorted(results_dir.glob("*/config.json")):
        setup = json.loads(config_file.read_text(encoding="utf-8"))
        if setup.get("completed") and setup.get("split") == split and not setup.get("rejudged_from"):
            found.append(config_file.parent)
    return found


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path, help="run folders to compare")
    parser.add_argument("--split", choices=("dev", "test", "holdout"), help="compare every completed run of this split")
    parser.add_argument("--results-dir", type=Path, default=runner.RESULTS_DIR)
    args = parser.parse_args(argv)
    run_dirs = args.runs or (runs_of_split(args.results_dir, args.split) if args.split else [])
    if not run_dirs:
        print("Give run folders or --split.", file=sys.stderr)
        return 1
    print(table(run_dirs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
