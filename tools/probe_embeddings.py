"""Redacted QuickML embedding capability probe.

The command reports only contract metadata. It never prints tokens, request
headers, or narrative text.
"""
import argparse
import json
import os
import time

from functions.crime_query.mo_embeddings import QuickMLMultilingualProvider


FIXTURE = ("ಕಳ್ಳತನ ನಡೆದಿದೆ", "theft occurred")


def probe(provider):
    started = time.monotonic()
    vectors = provider.embed_documents(FIXTURE)
    dimension = len(vectors[0]) if vectors else 0
    return {
        "status": "ok",
        "model": provider.model,
        "dimension": dimension,
        "batch_size": provider.batch_size,
        "latency_ms": round((time.monotonic() - started) * 1000, 2),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--language-fixture", action="store_true")
    args = parser.parse_args(argv)
    if not args.language_fixture:
        parser.error("--language-fixture is required")
    endpoint = os.environ.get("QUICKML_EMBEDDINGS_ENDPOINT")
    if not endpoint:
        print(json.dumps({"status": "error", "reason": "embedding endpoint is not configured"}))
        return 2
    try:
        provider = QuickMLMultilingualProvider(
            endpoint=endpoint,
            token=os.environ.get("QUICKML_TOKEN"),
            org_id=os.environ.get("QUICKML_ORG_ID"),
            model=os.environ.get("QUICKML_EMBEDDINGS_MODEL", "multilingual-v1"),
            timeout=float(os.environ.get("QUICKML_EMBEDDINGS_TIMEOUT", "10")),
            batch_size=int(os.environ.get("QUICKML_EMBEDDINGS_BATCH_SIZE", "32")),
        )
        print(json.dumps(probe(provider), sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status": "error", "reason": "embedding capability probe failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
