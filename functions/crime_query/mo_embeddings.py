"""Provider-neutral embeddings with a deterministic offline implementation."""
import hashlib
import math

try:
    import requests
except ImportError:  # pragma: no cover - Catalyst supplies requests
    requests = None


class EmbeddingError(Exception):
    pass


class UnavailableEmbeddingProvider:
    """Fail-closed provider used until the live endpoint is provisioned.

    Keeping this object constructible lets the silent-match function boot and
    continue structured/identity scoring. Callers receive one bounded error
    when semantic retrieval or indexing actually needs the unavailable
    capability; no endpoint, token, or narrative is exposed.
    """

    def embed_documents(self, texts):
        raise EmbeddingError("multilingual embedding provider is unavailable")


class QuickMLMultilingualProvider:
    """Small, validated adapter for the configured QuickML embedding endpoint."""

    def __init__(self, endpoint, token=None, org_id=None, transport=None,
                 model="multilingual-v1", timeout=10, batch_size=32):
        if not endpoint:
            raise ValueError("endpoint is required")
        if batch_size < 1 or timeout <= 0:
            raise ValueError("timeout and batch_size must be positive")
        self.endpoint = endpoint
        self.token = token
        self.org_id = org_id
        self.model = model
        self.timeout = timeout
        self.batch_size = batch_size
        self.transport = transport or (requests.Session() if requests else None)
        if self.transport is None:
            raise EmbeddingError("HTTP transport is unavailable")

    def embed_documents(self, texts):
        values = list(texts)
        if not values:
            return []
        if len(values) > self.batch_size:
            raise EmbeddingError("embedding batch exceeds configured limit")
        payload = {"texts": [str(value or "") for value in values],
                   "model": self.model}
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Zoho-oauthtoken " + self.token
        if self.org_id:
            headers["X-ZOHO-ORGID"] = str(self.org_id)
        try:
            response = self.transport.post(
                self.endpoint, json=payload, headers=headers,
                timeout=self.timeout,
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            body = response.json() if hasattr(response, "json") else response
        except Exception as exc:
            raise EmbeddingError("QuickML embedding request failed") from exc
        vectors = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(values):
            raise EmbeddingError("QuickML response vector count mismatch")
        normalized = []
        dimension = None
        for vector in vectors:
            if not isinstance(vector, list) or not vector:
                raise EmbeddingError("QuickML response contains an invalid vector")
            if dimension is None:
                dimension = len(vector)
            if len(vector) != dimension or not all(isinstance(v, (int, float)) for v in vector):
                raise EmbeddingError("QuickML response contains inconsistent vectors")
            norm = math.sqrt(sum(float(value) ** 2 for value in vector))
            if not norm:
                raise EmbeddingError("QuickML response contains a zero vector")
            normalized.append([float(value) / norm for value in vector])
        return normalized


class DeterministicEmbeddingProvider:
    def __init__(self, dimension=64):
        if dimension < 2:
            raise ValueError("dimension must be at least 2")
        self.dimension = dimension

    def embed_documents(self, texts):
        vectors = []
        for text in texts:
            values = [0.0] * self.dimension
            for token in str(text or "").casefold().split():
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimension
                values[index] += 1.0 if digest[4] % 2 else -1.0
            norm = math.sqrt(sum(value * value for value in values))
            if not norm:
                raise EmbeddingError("cannot index an empty narrative")
            vectors.append([value / norm for value in values])
        return vectors
