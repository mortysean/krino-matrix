"""Pinned inputs: the dataset revision, the test file's hash and the model revision.

Only all/test-*.parquet is downloaded; the train split never reaches this process.
"""
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import snapshot_download
from pydantic import BaseModel

DATASET = "LocalLLaMA/typed-decisions"
DATASET_REVISION = "9ee69423ce0b0568c2d2d86e92c72ed7952fd084"
TEST_FILE = "all/test-00000-of-00001.parquet"
TEST_SHA256 = "4f294f218ea1da27f3efef936359389c62ea4d3973a41457732990f1d31b647c"
OFFICIAL_SCORER = "bench/score_with_jobs.py"     # downloaded to read the metric definitions, never executed

MODEL_REPO = "yuxiaohuang2004/krino_matrix"      # checkpoints/exp/exp_C_opus1000_base_e20
MODEL_REVISION = "79dc1368f0d13c27977a20aee18e0bd7f0612fa1"
MODEL_FILES = ["config.json", "head.pt", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
               "value_config.json"]


class BenchCase(BaseModel):
    """One test row. state and questions are model input; gold is only ever read by the metrics."""
    id: str
    workflow: str
    state: dict
    questions: dict[str, dict]
    gold: dict[str, dict]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_test() -> tuple[list[BenchCase], dict]:
    """The pinned test split, refused if its bytes differ from the pinned hash."""
    root = Path(snapshot_download(DATASET, repo_type="dataset", revision=DATASET_REVISION,
                                  allow_patterns=[TEST_FILE, OFFICIAL_SCORER]))
    digest = sha256(root / TEST_FILE)
    if digest != TEST_SHA256:
        raise RuntimeError(f"{TEST_FILE} sha256 {digest} != pinned {TEST_SHA256}")
    rows = pq.read_table(root / TEST_FILE).to_pylist()
    if any(r["split"] != "test" for r in rows):
        raise RuntimeError("non-test rows in the test file")
    cases = [BenchCase(id=r["id"], workflow=r["workflow"], state=json.loads(r["state"]),
                       questions=json.loads(r["questions"]), gold=json.loads(r["gold"])) for r in rows]
    return cases, {"dataset": DATASET, "revision": DATASET_REVISION, "config": "all", "split": "test",
                   "file": TEST_FILE, "sha256": digest, "official_scorer": OFFICIAL_SCORER}


def load_model() -> tuple[str, dict]:
    """Local directory of the pinned model revision, with each file's hash."""
    root = Path(snapshot_download(MODEL_REPO, revision=MODEL_REVISION, allow_patterns=MODEL_FILES))
    return str(root), {"repo": MODEL_REPO, "revision": MODEL_REVISION,
                       "sha256": {f: sha256(root / f) for f in MODEL_FILES}}
