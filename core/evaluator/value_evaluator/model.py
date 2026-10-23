import json
from pathlib import Path

import torch
from torch import nn
from transformers import AutoModel, AutoTokenizer

from ...schema import State, Action

DEFAULT_BACKBONE = "BAAI/bge-small-zh-v1.5"
HEAD_FILE = "head.pt"


def as_text(
    state: State,
    objective: str,
    action: Action
) -> tuple[str, str]:
    """The (first, second) text pair the model reads. Only the state goes second, so only it gets truncated."""
    first = f"Objective: {objective}\nAction: {action.id}\n{action.description}"
    second = json.dumps(state.data, ensure_ascii=False)
    return first, second


class ValueModel(nn.Module):
    """Encoder + linear head: one forward pass maps (state, objective, action) to a scalar value.

    path is a Hugging Face backbone name, or a directory written by save(); the head is
    freshly initialized for a backbone and restored for a saved model.
    """

    def __init__(
        self,
        path: str = DEFAULT_BACKBONE,
        max_length: int = 512
    ):
        super().__init__()
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.encoder = AutoModel.from_pretrained(path)
        self.head = nn.Linear(self.encoder.config.hidden_size, 1)
        head_file = Path(path) / HEAD_FILE
        if head_file.exists():
            self.head.load_state_dict(torch.load(head_file, map_location="cpu", weights_only=True))

    def forward(
        self,
        pairs: list[tuple[str, str]]
    ) -> torch.Tensor:
        """Text pairs from as_text → scores of shape (batch,)."""
        inputs = self.tokenizer(
            [first for first, _ in pairs],
            [second for _, second in pairs],
            truncation="only_second",
            max_length=self.max_length,
            padding=True,
            return_tensors="pt",
        ).to(self.head.weight.device)
        hidden = self.encoder(**inputs).last_hidden_state
        return self.head(hidden[:, 0]).squeeze(-1)      # [CLS] pooling

    def save(
        self,
        path: str
    ):
        self.tokenizer.save_pretrained(path)
        self.encoder.save_pretrained(path)
        torch.save(self.head.state_dict(), Path(path) / HEAD_FILE)
