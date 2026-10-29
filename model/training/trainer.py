"""Joint training of the three heads of a MatrixModel on Krino Matrix cases.

Per task, over the labels a batch carries (a missing label is masked out, never read as 0):
  goal         soft cross-entropy against the goal distribution + 0.1 × squared error of the expected level
  constraints  binary cross-entropy against P(violation), averaged over the labeled (action, constraint) pairs
  selection    soft cross-entropy against the best distribution over the action space
A task with no label in a batch is left out of that batch's loss. The task losses are combined either with
fixed weights (goal 1, constraints 1, selection 0.5) or by uncertainty weighting (Kendall et al., 2018):
  total = Σ 0.5 · exp(−s_i) · L_i + 0.5 · s_i
with s_i = log σ_i² learned with the model from 0. The effective weight of a task is then 0.5 · exp(−s_i).
Epochs are chosen on the val split by the unweighted sum of the task losses, which both weightings share.
TrainConfig.tasks trains a subset of the heads, for ablations: the other tasks never enter the loss or the epoch
choice, and the saved config records which heads were trained.
"""
import json
import math
import random
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import torch
from torch import nn

from krino.common.matrix import MatrixCase
from ..network import MatrixModel, TASKS

FIXED_WEIGHTS = {"goal": 1.0, "constraints": 1.0, "selection": 0.5}
TEMP_MIN, TEMP_MAX = 0.5, 5.0


@dataclass
class TrainConfig:
    weighting: str = "uncertainty"            # "uncertainty" or "fixed"
    fixed_weights: dict = field(default_factory=lambda: dict(FIXED_WEIGHTS))
    goal_mse_weight: float = 0.1
    epochs: int = 4
    micro_batch: int = 2
    grad_accum: int = 16
    encoder_lr: float = 2.5e-5
    head_lr: float = 1e-4
    log_var_lr: float = 5e-3
    weight_decay: float = 0.01
    warmup: float = 0.05
    grad_clip: float = 1.0
    freeze_below: int = 0                     # freeze the embeddings and this many encoder layers
    shuffle: bool = True                      # present actions and constraints in a fresh order every epoch
    log_every: int = 20
    seed: int = 0
    tasks: tuple = TASKS                      # the heads to train; the others stay untrained


class TaskWeighting(nn.Module):
    def __init__(self, config: TrainConfig):
        super().__init__()
        self.config = config
        # One log variance per task, from 0; trained only under uncertainty weighting
        self.log_vars = nn.Parameter(torch.zeros(len(TASKS)), requires_grad=config.weighting == "uncertainty")

    def weights(self) -> dict[str, float]:
        if self.config.weighting == "fixed":
            return dict(self.config.fixed_weights)
        return {t: float(0.5 * torch.exp(-s)) for t, s in zip(TASKS, self.log_vars.detach())}

    def forward(self, losses: dict[str, torch.Tensor]) -> torch.Tensor:
        """The weighted total over the tasks present in `losses`."""
        total = 0.0
        for i, task in enumerate(TASKS):
            if task not in losses:
                continue
            if self.config.weighting == "fixed":
                total = total + self.config.fixed_weights[task] * losses[task]
            else:
                s = self.log_vars[i]
                total = total + 0.5 * torch.exp(-s) * losses[task] + 0.5 * s
        return total


def targets(
    cases: list[MatrixCase],
    orders: list[tuple[list, list]],
    n_levels: int
) -> dict[str, torch.Tensor]:
    """Label tensors aligned with the encoded order of every case, with masks for the labels it lacks."""
    b = len(cases)
    n = max(len(a) for a, _ in orders)
    m = max(1, max(len(c) for _, c in orders))
    out = {
        "goal": torch.zeros(b, n, n_levels), "goal_mask": torch.zeros(b, n, dtype=torch.bool),
        "constraints": torch.zeros(b, n, m), "constraints_mask": torch.zeros(b, n, m, dtype=torch.bool),
        "selection": torch.zeros(b, n), "selection_mask": torch.zeros(b, dtype=torch.bool),
    }
    for i, (case, (actions, constraints)) in enumerate(zip(cases, orders)):
        labels = case.labels
        for j, a in enumerate(actions):
            if a.id in labels.goal:
                out["goal"][i, j] = torch.tensor(labels.goal[a.id])
                out["goal_mask"][i, j] = True
            for k, c in enumerate(constraints):
                p = labels.constraints.get(a.id, {}).get(c.id)
                if p is not None:
                    out["constraints"][i, j, k] = p
                    out["constraints_mask"][i, j, k] = True
        if labels.best:
            out["selection"][i, :len(actions)] = torch.tensor([labels.best[a.id] for a in actions])
            out["selection_mask"][i] = True
    return out


def task_losses(
    logits: dict[str, torch.Tensor],
    target: dict[str, torch.Tensor],
    goal_mse_weight: float
) -> dict[str, torch.Tensor]:
    """The loss of every task that has at least one label in the batch."""
    device = logits["goal"].device
    target = {k: v.to(device) for k, v in target.items()}
    losses = {}
    mask = target["goal_mask"]
    if mask.any():
        log_p = torch.log_softmax(logits["goal"][mask], -1)
        gold = target["goal"][mask]
        levels = torch.arange(gold.size(-1), device=device, dtype=log_p.dtype)
        ce = -(gold * log_p).sum(-1).mean()
        mse = (((log_p.exp() * levels).sum(-1) - (gold * levels).sum(-1)) ** 2).mean()
        losses["goal"] = ce + goal_mse_weight * mse
    mask = target["constraints_mask"]
    if mask.any():
        losses["constraints"] = nn.functional.binary_cross_entropy_with_logits(
            logits["constraints"][mask], target["constraints"][mask])
    mask = target["selection_mask"]
    if mask.any():
        log_p = torch.log_softmax(logits["selection"][mask], -1)
        losses["selection"] = -(target["selection"][mask] * log_p).sum(-1).mean()
    return losses


def ordered(case: MatrixCase, rng: random.Random | None) -> tuple[list, list]:
    actions, constraints = list(case.action_space), list(case.constraints)
    if rng:
        rng.shuffle(actions)
        rng.shuffle(constraints)
    return actions, constraints


def batches(model: MatrixModel, cases: list[MatrixCase], size: int, rng: random.Random | None):
    """(batch, target) per micro-batch; with rng, cases and their items come in a fresh order."""
    n_levels = model.goal_head[-1].out_features
    order = list(range(len(cases)))
    if rng:
        rng.shuffle(order)
    for start in range(0, len(order), size):
        chunk = [cases[i] for i in order[start:start + size]]
        orders = [ordered(c, rng) for c in chunk]
        encoded = [model.encode(c.problem().model_copy(update={"constraints": constraints}), actions)
                   for c, (actions, constraints) in zip(chunk, orders)]
        yield model.collate(encoded), targets(chunk, orders, n_levels)


@torch.no_grad()
def validate(model: MatrixModel, cases: list[MatrixCase], config: TrainConfig) -> dict[str, float]:
    """Mean unweighted task losses over val, each over the cases that carry its labels."""
    model.eval()
    device = model.temperature.device
    sums, counts = {t: 0.0 for t in TASKS}, {t: 0 for t in TASKS}
    for batch, target in batches(model, cases, config.micro_batch, None):
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            logits = model(batch)
        size = len(target["selection_mask"])
        for task, loss in task_losses(logits, target, config.goal_mse_weight).items():
            if task not in config.tasks:
                continue
            sums[task] += float(loss) * size
            counts[task] += size
    out = {t: sums[t] / counts[t] for t in TASKS if counts[t]}
    out["sum"] = sum(out.values())
    model.train()
    return out


def train(
    model: MatrixModel,
    cases: list[MatrixCase],
    val: list[MatrixCase],
    config: TrainConfig,
    out: str | Path
) -> dict:
    """Train in place, keep the epoch with the lowest val loss sum in `out`, and return the run history.
    Every log_every optimizer steps, `out`/train_log.jsonl records the raw task losses, their effective weights
    and the total loss."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(config.seed)
    device = model.temperature.device
    model.config["tasks"] = list(config.tasks)
    if config.freeze_below:
        model.encoder.embeddings.requires_grad_(False)
        for layer in model.encoder.layers[:config.freeze_below]:
            layer.requires_grad_(False)
    model.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.checkpointing = True
    weighting = TaskWeighting(config).to(device)
    groups = [
        {"params": [p for p in model.encoder.parameters() if p.requires_grad], "lr": config.encoder_lr},
        {"params": [p for n, p in model.named_parameters() if not n.startswith("encoder.") and p.requires_grad],
         "lr": config.head_lr},
    ]
    if config.weighting == "uncertainty":
        groups.append({"params": [weighting.log_vars], "lr": config.log_var_lr, "weight_decay": 0.0})
    optimizer = torch.optim.AdamW(groups, weight_decay=config.weight_decay)
    steps = math.ceil(math.ceil(len(cases) / config.micro_batch) / config.grad_accum) * config.epochs
    warmup = max(1, int(steps * config.warmup))
    def schedule(s: int) -> float:
        """Linear warmup, then cosine decay to 0."""
        if s < warmup:
            return (s + 1) / warmup
        return 0.5 * (1 + math.cos(math.pi * min(1.0, (s - warmup) / max(1, steps - warmup))))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, schedule)
    trainable = sum(p.numel() for g in groups for p in g["params"])
    print(f"train {len(cases)} cases, val {len(val)}; {steps} optimizer steps; {trainable / 1e6:.0f}M trainable; "
          f"weighting {config.weighting}", flush=True)

    log = (out / "train_log.jsonl").open("w", encoding="utf-8")
    history, best = [], None
    rng = random.Random(config.seed)
    step = 0
    window = {t: [] for t in TASKS} | {"total": []}
    model.train()
    start = time.time()
    for epoch in range(1, config.epochs + 1):
        optimizer.zero_grad(set_to_none=True)
        for i, (batch, target) in enumerate(batches(model, cases, config.micro_batch, rng if config.shuffle else None), 1):
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(batch)
            losses = {t: v for t, v in task_losses(logits, target, config.goal_mse_weight).items() if t in config.tasks}
            if not losses:
                continue
            total = weighting(losses)
            (total / config.grad_accum).backward()
            for task, loss in losses.items():
                window[task].append(float(loss))
            window["total"].append(float(total))
            if i % config.grad_accum:
                continue
            torch.nn.utils.clip_grad_norm_([p for g in groups for p in g["params"]], config.grad_clip)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            if step % config.log_every == 0:
                record = {"step": step, "epoch": epoch, "lr": scheduler.get_last_lr()[0],
                          "loss": {k: sum(v) / len(v) for k, v in window.items() if v},
                          "weight": weighting.weights(), "elapsed_s": round(time.time() - start)}
                log.write(json.dumps(record) + "\n")
                log.flush()
                print(f"step {step}/{steps} epoch {epoch} " + " ".join(f"{k} {v:.4f}" for k, v in record["loss"].items())
                      + " | weights " + " ".join(f"{k} {v:.3f}" for k, v in record["weight"].items()), flush=True)
                window = {t: [] for t in TASKS} | {"total": []}
        val_loss = validate(model, val, config)
        record = {"epoch": epoch, "step": step, "val": val_loss, "weight": weighting.weights(),
                  "elapsed_s": round(time.time() - start)}
        history.append(record)
        log.write(json.dumps(record) + "\n")
        log.flush()
        print(f"epoch {epoch} val " + " ".join(f"{k} {v:.4f}" for k, v in val_loss.items()), flush=True)
        if best is None or val_loss["sum"] < best["val"]["sum"]:
            best = record
            model.save(out)
    log.close()
    summary = {"config": asdict(config), "history": history, "best_epoch": best["epoch"]}
    (out / "train_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


@torch.no_grad()
def calibrate(model: MatrixModel, val: list[MatrixCase], micro_batch: int = 4) -> list[float]:
    """One temperature per task, by grid search for the lowest val loss of that task on the raw logits."""
    model.eval()
    device = model.temperature.device
    collected = {t: [] for t in TASKS}
    for batch, target in batches(model, val, micro_batch, None):
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            logits = {k: v.cpu() for k, v in model(batch).items()}
        for task, key in (("goal", "goal"), ("constraints", "constraints"), ("selection", "selection")):
            mask = target[f"{key}_mask"]
            collected[task].append((logits[key][mask], target[key][mask]))
    grid = torch.linspace(TEMP_MIN, TEMP_MAX, 91)
    temperatures = []
    for task in TASKS:
        if task == "selection":
            # Batches differ in action count: pad like forward() does, to -1e4 logits and 0 targets
            n = max((z.size(-1) for z, _ in collected[task]), default=0)
            collected[task] = [(nn.functional.pad(z, (0, n - z.size(-1)), value=-1e4),
                                nn.functional.pad(y, (0, n - y.size(-1)))) for z, y in collected[task]]
        z = torch.cat([z for z, _ in collected[task]]) if collected[task] else torch.empty(0)
        y = torch.cat([y for _, y in collected[task]]) if collected[task] else torch.empty(0)
        if not len(z):
            temperatures.append(1.0)
            continue

        def nll(t: float) -> float:
            if task == "constraints":
                return float(nn.functional.binary_cross_entropy_with_logits(z / t, y))
            return float(-(y * torch.log_softmax(z / t, -1)).sum(-1).mean())

        temperatures.append(float(min(grid, key=lambda t: nll(float(t)))))
    model.temperature.copy_(torch.tensor(temperatures))
    return temperatures
