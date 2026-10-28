"""Connects the Decision Core to concrete models: the generation LLM and the evaluator.

Configured from .env:
  LLM_DEFAULT / LLM_PROVIDERS   the generation model (see .env.example)
  KRINO_EVALUATOR               baseline (default) or matrix
  KRINO_MATRIX_CHECKPOINT       checkpoint directory for the matrix evaluator
"""
import os
from pathlib import Path

from core.formulator.api_formulator import APIFormulator
from decision_core import Clarifier, CardGenerator, DecisionEngine
from decision_core.ranker import Ranker
from .llm import Call, CallLog, TracedLLM, current_log, model_configured
from .rankers import BaselineRanker, MatrixRanker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKPOINT = ROOT / "experiments/krino-matrix-v1/checkpoints/multilingual-uncertainty"


def make_ranker(llm: TracedLLM) -> Ranker:
    mode = os.getenv("KRINO_EVALUATOR", "baseline").lower()
    if mode == "matrix":
        path = Path(os.getenv("KRINO_MATRIX_CHECKPOINT") or DEFAULT_CHECKPOINT)
        if not (path / "matrix_config.json").exists():
            raise FileNotFoundError(f"KRINO_EVALUATOR=matrix but no checkpoint at {path}")
        return MatrixRanker(str(path))
    return BaselineRanker(llm)


def build_engine() -> DecisionEngine:
    llm = TracedLLM()
    return DecisionEngine(APIFormulator(llm), Clarifier(llm), CardGenerator(llm), make_ranker(llm),
                          generator_version=llm.version)


__all__ = ["Call", "CallLog", "TracedLLM", "current_log", "model_configured", "BaselineRanker", "MatrixRanker",
           "make_ranker", "build_engine"]
