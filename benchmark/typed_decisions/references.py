"""Publicly reported numbers, copied from their sources at the pinned revisions. Not measured here.

"definition" says whose metric definitions a number uses (see metrics.py): accuracy agrees across
both; Brier and ECE do not (Laya: choice + noul only, 15 bins; official: all decisions, 10 bins).
"""
DATASET_CARD = ("https://huggingface.co/datasets/LocalLLaMA/typed-decisions "
                "(README.md @ 9ee69423ce0b0568c2d2d86e92c72ed7952fd084)")
LAYA_CARD = ("https://huggingface.co/convaiinnovations/laya-typed-decisions "
             "(README.md @ e929ae5cf69bc34259cd2f95c9e91145b818b1f0)")

REFERENCES = [
    {
        "name": "Laya Base",
        "model": "convaiinnovations/laya (ModernBERT-large, 421M, not fine-tuned)",
        "mode": "zero-shot",
        "definition": "laya",
        "overall": {"accuracy": 0.362, "soft_accuracy": 0.332, "brier": 0.316, "ece": 0.175, "score_mae": 0.694},
        "by_type": {}, "by_workflow": {},
        "source": LAYA_CARD,
    },
    {
        "name": "Laya fine-tuned",
        "model": "convaiinnovations/laya-typed-decisions (ModernBERT-large, 421M, RLCD on the 1,200-case train split)",
        "mode": "fitted on train (dataset card's second table; not comparable with zero-shot rows)",
        "definition": "laya",
        "overall": {"accuracy": 0.766, "soft_accuracy": 0.471, "brier": 0.062, "ece": 0.213, "score_mae": 0.242},
        "by_type": {"noul": {"accuracy": 0.857, "ece": 0.192}, "choice": {"accuracy": 0.733, "ece": 0.255},
                    "score": {"accuracy": 0.723, "ece": 0.199}},
        "by_workflow": {"invoice_processing": {"accuracy": 0.804}, "security_incidents": {"accuracy": 0.766},
                        "customer_service": {"accuracy": 0.764}, "agent_trace_observability": {"accuracy": 0.730}},
        "source": LAYA_CARD + "; accuracy also in " + DATASET_CARD,
    },
    {
        "name": "JEV 1.13.0",
        "model": "TypeSafe Jev 1.13.0 (API)",
        "mode": "zero-shot",
        "definition": "official",
        "overall": {"accuracy": 0.727, "kl_from_gold": 1.442, "brier": 0.148, "ece": 0.144, "p50_latency_ms": 710,
                    "soft_accuracy": 0.580, "score_mae": 0.391},
        "by_type": {"noul": {"accuracy": 0.775}, "choice": {"accuracy": 0.720}, "score": {"accuracy": 0.696}},
        "by_workflow": {},
        "source": (DATASET_CARD + " (accuracy, KL, Brier, ECE, p50 latency, per-type accuracy); soft accuracy and "
                   "score MAE as cited by " + LAYA_CARD + ", third-party"),
    },
]

# The dataset card's two input-free baselines; Uniform is recomputed here to check the metric code.
BASELINES = {
    "Prior (ignores the input)": {"accuracy": 0.470, "kl_from_gold": 0.347, "brier": 0.189, "ece": 0.088},
    "Uniform": {"accuracy": 0.308, "kl_from_gold": 0.444, "brier": 0.238, "ece": 0.169},
}
