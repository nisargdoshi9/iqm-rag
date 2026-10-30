"""Imported for its side effect by tests that build a retriever or a chain: tracing must never reach the network in tests,
even if a developer has LANGSMITH_TRACING=true in their .env."""

import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
