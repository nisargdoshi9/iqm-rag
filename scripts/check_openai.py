"""One-off check that the OpenAI key and embedding model work (one small request, a fraction of a cent).

    python scripts/check_openai.py
"""

import sys

from openai import OpenAI, OpenAIError

from iqm_rag import config

SAMPLE_TEXTS = [
    "How do I upload an audio creative?",
    "Daily Pacing updates every hour.",
    "Set a campaign's daily budget.",
]


def main() -> int:
    try:
        client = OpenAI(api_key=config.openai_api_key())
        model = config.embedding_model()
        response = client.embeddings.create(model=model, input=SAMPLE_TEXTS)
    except (RuntimeError, OpenAIError) as exc:
        print(f"OpenAI check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"model: {model}")
    print(f"vectors: {len(response.data)}, dimension: {len(response.data[0].embedding)}")
    print(f"tokens used: {response.usage.total_tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
