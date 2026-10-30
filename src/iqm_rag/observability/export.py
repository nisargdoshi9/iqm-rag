"""Export one trace from LangSmith as a nested JSON document (FR-8), so a reviewer without access to our LangSmith project
can see exactly what a request recorded: the retrieved chunks, the prompts, the responses, latency and token usage.

Costs are LangSmith's own estimate from the model's published prices, not a billed amount.
"""

import json
from typing import Any, Optional

from iqm_rag import config

OMITTED_METADATA = ("revision_id", "ls_run_depth", "ls_method", "LANGSMITH_PROJECT", "LANGSMITH_TRACING")


def _seconds(run) -> Optional[float]:
    if run.start_time is None or run.end_time is None:
        return None
    return round((run.end_time - run.start_time).total_seconds(), 3)


def run_to_dict(run) -> dict[str, Any]:
    metadata = {k: v for k, v in ((getattr(run, "extra", None) or {}).get("metadata") or {}).items() if k not in OMITTED_METADATA}
    cost = getattr(run, "total_cost", None)
    return {
        "id": str(run.id), "name": run.name, "run_type": run.run_type, "latency_seconds": _seconds(run),
        "tokens": {"prompt": run.prompt_tokens, "completion": run.completion_tokens, "total": run.total_tokens},
        "estimated_cost_usd": None if cost is None else float(cost), "tags": list(run.tags or []), "metadata": metadata,
        "inputs": run.inputs, "outputs": run.outputs, "error": run.error, "children": [],
    }


def _is_wrapper(run) -> bool:
    """LangChain's own composition runs (RunnableSequence, RunnableParallel, ...): they repeat their children's data."""
    return run.name.startswith("Runnable") and run.parent_run_id is not None


def build_tree(runs: list) -> dict[str, Any]:
    """Nest the runs of one trace under their parents, children in start order. LangChain's wrapper runs are left out and
    their children attach to the nearest real step, which keeps the export readable. Returns the root."""
    by_id = {str(run.id): run for run in runs}
    nodes = {key: run_to_dict(run) for key, run in by_id.items() if not _is_wrapper(run)}

    def real_parent(run) -> Optional[str]:
        parent = None if run.parent_run_id is None else str(run.parent_run_id)
        while parent is not None and parent in by_id and _is_wrapper(by_id[parent]):
            grand = by_id[parent].parent_run_id
            parent = None if grand is None else str(grand)
        return parent

    root = None
    for run in sorted(runs, key=lambda r: r.start_time):
        if _is_wrapper(run):
            continue
        parent = real_parent(run)
        if parent is None or parent not in nodes:
            root = root or nodes[str(run.id)]
        else:
            nodes[parent]["children"].append(nodes[str(run.id)])
    if root is None:
        raise ValueError("The trace has no root run.")
    return root


def fetch_trace(trace_id: str, project: Optional[str] = None) -> dict[str, Any]:
    from langsmith import Client

    runs = list(Client().list_runs(project_name=project or config.langsmith_project(), trace_id=trace_id))
    if not runs:
        raise LookupError(f"No runs found for trace {trace_id} in project {project or config.langsmith_project()}. "
                          "Traces can take a few seconds to appear.")
    return build_tree(runs)


def to_json(tree: dict[str, Any]) -> str:
    return json.dumps(tree, indent=2, ensure_ascii=False, default=str)
