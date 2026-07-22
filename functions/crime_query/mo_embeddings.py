"""Provider-neutral embeddings with a deterministic offline implementation."""
import hashlib
import math


class EmbeddingError(Exception):
    pass


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
