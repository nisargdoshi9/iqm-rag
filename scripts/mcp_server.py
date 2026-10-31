"""Run the IQM Help Center MCP server over stdio (bonus: MCP server).

Needs the index built (python scripts/index.py) and OPENAI_API_KEY in .env (queries are embedded and reranked with it).
Add it to an MCP client, for example Claude Desktop (claude_desktop_config.json):

    {"mcpServers": {"iqm-help-center": {"command": "/path/to/repo/.venv/bin/python", "args": ["/path/to/repo/scripts/mcp_server.py"]}}}

or Claude Code:  claude mcp add iqm-help-center -- /path/to/repo/.venv/bin/python /path/to/repo/scripts/mcp_server.py

Tools: search_help_center(query, top_k) and get_article(article, max_chars, offset). Settings come from .env (RETRIEVAL_MODE, RERANK, ...).
Restart the client after scripts/update.py so the server loads the new index. All logging goes to stderr: stdout carries the protocol.
"""

import logging
import sys

from iqm_rag.mcp_server import build_server


def main() -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
    build_server().run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
