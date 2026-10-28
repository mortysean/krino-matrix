"""Training, calibration and evaluation of the ValueModel, following Laya's laya/train.py and laya/calibrate.py:
RLCD (policy gradient on noisy logits rewarded by strictly proper scoring rules, plus soft cross-entropy),
then one temperature fitted on a held-out slice."""
import math
import random

import numpy as np
import torch
from ...schema import State
from ...matrix import MatrixCase
from .model import ValueModel, TEMP_MIN, TEMP_MAX, expected_value


def items(
    model: ValueModel,
    cases: list[MatrixCase]
) -> list[tuple[tuple[list[int], list[int]], list[float], int]]:
    """(encoded, normalized target, case index) per action with a value label; the model reads the zh rubric."""
    out = []
    for i, case in enumerate(cases):
        if case.lang != "zh":
            continue
        for action in case.action_space:
            target = case.labels.goal.get(action.id)
            if target is None or len(target) != len(model.levels) or sum(target) <= 0:
                continue
            total = sum(target)
            out.append((model.encode(State(data=case.state), case.goal, action), [t / total for t in target], i))
    return out


def proper_reward(
    q: torch.Tensor,
    target: torch.Tensor,
    w_sph: float,
    w_rps: float
) -> torch.Tensor:
    """Log score + spherical score − ranked probability score: maximized only by reporting the target."""
    log_score = (target * torch.log(q.clamp_min(1e-12)).clamp_min(-9.21)).sum(-1)
    spherical = (target * q).sum(-1) / q.norm(dim=-1).clamp_min(1e-9)
    rps = ((torch.cumsum(q, -1) - torch.cumsum(target, -1)) ** 2).sum(-1) / (q.size(-1) - 1)
    return log_score + w_sph * spherical - w_rps * rps


def rlcd_loss(
    logits: torch.Tensor,
    target: torch.Tensor,
    sigma: float,
    samples: int,
    w_sph: float,
    w_rps: float
) -> torch.Tensor:
    """Gaussian policy around the logits: samples are rewarded by proper_reward, the normalized advantage
    weights their log-density; plus soft cross-entropy against the target."""
    eps = torch.randn((samples,) + logits.shape, device=logits.device) * sigma
    eps = eps - eps.mean(-1, keepdim=True)
    z = logits.detach().unsqueeze(0) + eps
    with torch.no_grad():
        reward = proper_reward(torch.softmax(z, -1), target.unsqueeze(0), w_sph, w_rps)
        advantage = reward - reward.mean(0, keepdim=True)
        advantage = advantage / (advantage.std() + 1e-6)
    log_density = -((z - logits.unsqueeze(0)) ** 2).sum(-1) / (2 * sigma ** 2)
    soft_ce = -(target * torch.log_softmax(logits, -1)).sum(-1).mean()
    return -(advantage * log_density).mean() + soft_ce


def train(
    model: ValueModel,
    cases: list[MatrixCase],
    epochs: int = 4,
    micro_batch: int = 8,
    grad_accum: int = 8,
    encoder_lr: float = 2.5e-5,
    head_lr: float = 1e-4,
    min_lr: float = 1e-6,
    weight_decay: float = 0.01,
    grad_clip: float = 1.0,
    rl_samples: int = 4,
    sigma_start: float = 0.4,
    sigma_end: float = 0.1,
    w_sph: float = 0.75,
    w_rps: float = 1.0,
    freeze_encoder: bool = False,
    seed: int = 0
) -> ValueModel:
    """Laya's training loop and defaults. A small dataset needs more epochs to reach a similar number of updates."""
    data = items(model, cases)
    device = model.temperature.device
    amp = device.type == "cuda"
    if freeze_encoder:
        model.encoder.requires_grad_(False)
    groups = [{"params": [p for n, p in model.named_parameters() if not n.startswith("encoder.")], "lr": head_lr}]
    if not freeze_encoder:
        groups.append({"params": list(model.encoder.parameters()), "lr": encoder_lr})
    optimizer = torch.optim.AdamW(groups, weight_decay=weight_decay)
    steps = math.ceil(len(data) / micro_batch)
    updates = epochs * math.ceil(steps / grad_accum)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=updates, eta_min=min_lr)
    scaler = torch.amp.GradScaler("cuda") if amp else None
    params = [p for g in groups for p in g["params"]]
    print(f"{len(data)} items from {len(cases)} cases, {updates} optimizer updates over {epochs} epochs")

    torch.manual_seed(seed)
    model.train()
    if freeze_encoder:
        model.encoder.eval()
    for epoch in range(epochs):
        random.Random(seed + epoch).shuffle(data)
        sigma = sigma_start + (sigma_end - sigma_start) * epoch / max(1, epochs - 1)
        total = 0.0
        optimizer.zero_grad(set_to_none=True)
        for step, start in enumerate(range(0, len(data), micro_batch)):
            batch = data[start:start + micro_batch]
            target = torch.tensor([t for _, t, _ in batch], device=device)
            with torch.autocast(device.type, dtype=torch.float16, enabled=amp):
                logits = model([e for e, _, _ in batch])
            loss = rlcd_loss(logits.float(), target, sigma, rl_samples, w_sph, w_rps)
            window = min(grad_accum, steps - step // grad_accum * grad_accum)
            (scaler.scale(loss / window) if scaler else loss / window).backward()
            if (step + 1) % grad_accum == 0 or step + 1 == steps:
                if scaler:
                    scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(params, grad_clip)
                if scaler:
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
            total += loss.item()
        print(f"epoch {epoch + 1}/{epochs}: loss {total / steps:.4f} (sigma {sigma:.2f})")
    return model.eval()


@torch.no_grad()
def predict(
    model: ValueModel,
    cases: list[MatrixCase],
    batch_size: int = 32
) -> tuple[torch.Tensor, torch.Tensor, list[int]]:
    """Raw logits, targets and case indices for every labeled action."""
    data = items(model, cases)
    logits = [model([e for e, _, _ in data[i:i + batch_size]]).cpu() for i in range(0, len(data), batch_size)]
    return torch.cat(logits), torch.tensor([t for _, t, _ in data]), [c for _, _, c in data]


def calibrate(
    model: ValueModel,
    cases: list[MatrixCase]
) -> float:
    """Fit one temperature by NLL on held-out cases (never the training cases) and install it."""
    logits, target, _ = predict(model, cases)
    log_t = torch.zeros(1, requires_grad=True)
    optimizer = torch.optim.LBFGS([log_t], lr=0.1, max_iter=100)

    def closure():
        optimizer.zero_grad()
        loss = -(target * torch.log_softmax(logits / log_t.exp(), -1)).sum(-1).mean()
        loss.backward()
        return loss

    optimizer.step(closure)
    temperature = float(log_t.exp().clamp(TEMP_MIN, TEMP_MAX))
    model.temperature.fill_(temperature)
    return temperature


def ece(
    confidence: np.ndarray,
    correct: np.ndarray,
    bins: int = 15
) -> float:
    edges = np.linspace(0, 1, bins + 1)
    error = 0.0
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        selected = (confidence >= lo if i == 0 else confidence > lo) & (confidence <= hi)
        if selected.any():
            error += selected.mean() * abs(confidence[selected].mean() - correct[selected].mean())
    return float(error)


def evaluate(
    model: ValueModel,
    cases: list[MatrixCase]
) -> dict[str, float]:
    """Laya's metrics against the gold distribution (accuracy, KL, Brier, ECE), plus what a decision needs:
    the error of the expected value and how often two actions of the same case are put in the gold order."""
    logits, target, case_ids = predict(model, cases)
    p = torch.softmax(logits / model.temperature.cpu(), -1)
    correct = (p.argmax(-1) == target.argmax(-1)).float()
    value, gold_value = expected_value(p), expected_value(target)

    agree, pairs = 0, 0
    for i in range(len(case_ids)):
        for j in range(i + 1, len(case_ids)):
            if case_ids[i] == case_ids[j] and abs(gold_value[i] - gold_value[j]) > 0.05:
                pairs += 1
                agree += int((value[i] - value[j]) * (gold_value[i] - gold_value[j]) > 0)

    return {
        "items": len(case_ids),
        "accuracy": correct.mean().item(),
        "kl": (target * (torch.log(target.clamp_min(1e-12)) - torch.log(p.clamp_min(1e-12)))).sum(-1).mean().item(),
        "brier": ((p - target) ** 2).sum(-1).mean().item(),
        "ece": ece(p.max(-1).values.numpy(), correct.numpy()),
        "value_mae": (value - gold_value).abs().mean().item(),
        "pairwise_order": agree / pairs if pairs else float("nan"),
    }
