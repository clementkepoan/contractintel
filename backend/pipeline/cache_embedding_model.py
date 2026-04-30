from __future__ import annotations

from backend.pipeline.embeddings import embed_texts, embedding_model_ready

from backend.config import settings


def main() -> None:
    if not embedding_model_ready():
        raise SystemExit(f"Embedding model server cannot reach model: {settings.embedding_model_name}")
    vector = embed_texts(["embedding healthcheck"])
    dims = len(vector[0]) if vector else 0
    print(f"Verified embedding model: {settings.embedding_model_name}")
    print(f"Embedding endpoint: {settings.embedding_model_base_url}")
    print(f"Vector dimension: {dims}")


if __name__ == "__main__":
    main()
