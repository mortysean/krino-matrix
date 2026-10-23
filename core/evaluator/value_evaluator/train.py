import random
from pathlib import Path

import torch
import torch.nn.functional as F
from pydantic import BaseModel

from ...schema import State, Action
from .model import ValueModel, as_text


class Sample(BaseModel):
    """One labeled example: how good the action is for the objective in the state."""
    state: State
    objective: str
    action: Action
    score: float


def load_samples(
    path: str
) -> list[Sample]:
    """One Sample per line of a JSONL file."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [Sample.model_validate_json(line) for line in lines if line.strip()]


def train(
    model: ValueModel,
    samples: list[Sample],
    epochs: int = 3,
    batch_size: int = 8,
    lr: float = 2e-5
) -> ValueModel:
    """Regress the model's output onto the sample scores with MSE."""
    device = next(model.parameters()).device
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    samples = list(samples)
    model.train()
    for epoch in range(epochs):
        random.shuffle(samples)
        total = 0.0
        for i in range(0, len(samples), batch_size):
            batch = samples[i:i + batch_size]
            pred = model([as_text(s.state, s.objective, s.action) for s in batch])
            target = torch.tensor([s.score for s in batch], device=device)
            loss = F.mse_loss(pred, target)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += loss.item() * len(batch)
        print(f"epoch {epoch + 1}/{epochs}: loss {total / len(samples):.4f}")
    return model.eval()
