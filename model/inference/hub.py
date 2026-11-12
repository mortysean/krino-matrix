"""The published Matrix checkpoint on Hugging Face: https://huggingface.co/yuxiaohuang2004/krino_matrix

  path = download()                     # cached after the first call
  evaluator = MatrixEvaluator(path)

In mainland China set HF_ENDPOINT=https://hf-mirror.com, or pass endpoint=.
"""
from ..network import hub_client

REPO = "yuxiaohuang2004/krino_matrix"
CHECKPOINT = "matrix-mmbert"    # the same weights the KRINO WORLD interaction policy runs


def download(
    repo: str = REPO,
    checkpoint: str = CHECKPOINT,
    endpoint: str | None = None,
    revision: str | None = None
) -> str:
    """Download one checkpoint directory of the model repo and return its local path."""
    from huggingface_hub import snapshot_download

    with hub_client(endpoint):
        root = snapshot_download(repo, allow_patterns=f"{checkpoint}/*", revision=revision)
    return f"{root}/{checkpoint}"
