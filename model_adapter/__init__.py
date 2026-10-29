"""Connects the Decision Core to concrete models: the generation LLM and the evaluator.

Configured from .env:
  LLM_DEFAULT / LLM_PROVIDERS   the generation model (see .env.example)
  KRINO_MATRIX_CHECKPOINT       checkpoint directory of the Matrix evaluator (default: the mmBERT-base model)
"""
import os
from pathlib import Path

from core.formulator import APIFormulator
from decision_core import Clarifier, CardGenerator, DecisionEngine
from .llm import Call, CallLog, TracedLLM, current_log, model_configured
from .rankers import MatrixRanker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKPOINT = ROOT / "experiments/krino-matrix-v1-mmbert/checkpoints/mmbert-uncertainty"


def make_ranker() -> MatrixRanker:
    path = Path(os.getenv("KRINO_MATRIX_CHECKPOINT") or DEFAULT_CHECKPOINT)
    if not (path / "matrix_config.json").exists():
        raise FileNotFoundError(f"no Matrix checkpoint at {path}")
    return MatrixRanker(str(path))


def build_engine() -> DecisionEngine:
    llm = TracedLLM()
    return DecisionEngine(APIFormulator(llm), Clarifier(llm), CardGenerator(llm), make_ranker(),
                          generator_version=llm.version)


__all__ = ["Call", "CallLog", "TracedLLM", "current_log", "model_configured", "MatrixRanker",
           "make_ranker", "build_engine"]
