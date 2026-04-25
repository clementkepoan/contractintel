from __future__ import annotations

from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer

from backend.config import settings


def main() -> None:
    local_path = snapshot_download(settings.embedding_model_name)
    SentenceTransformer(local_path)
    print(f"Cached embedding model: {settings.embedding_model_name}")
    print(f"Cache path: {local_path}")


if __name__ == "__main__":
    main()
