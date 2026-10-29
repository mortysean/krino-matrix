"""The Krino Matrix decision model: one shared encoder reads a whole case, three heads answer its tasks.

Sequence, one per case:
  [CLS] goal [SEP] [MASK] constraint 1 [MASK] constraint 2 ... [SEP] [MASK] action 1 [MASK] action 2 ... [SEP] state [SEP]
The encoder and a small transformer refine the sequence, then:
  goal head        each action's [MASK] → logits over the goal levels                       (N × LEVELS)
  constraint head  each (action, constraint) pair of [MASK]s → logit of P(violation)        (N × M)
  selection head   each action's [MASK] → one logit, softmaxed over the action space         (N)
The state goes last, so a long one is cut from its end; constraint and action texts are capped per item.
"""
import json
import os
from contextlib import contextmanager
from pathlib import Path

import torch
from torch import nn
from torch.utils.checkpoint import checkpoint
from transformers import AutoModel, AutoTokenizer

from krino.common.matrix import LEVELS
from krino.common.schema import Problem, Action

CONFIG_FILE = "matrix_config.json"
HEADS_FILE = "heads.pt"
KINDS = {"other": 0, "constraint": 1, "action": 2}
TASKS = ("goal", "constraints", "selection")


def mlp(d_in: int, d: int, d_out: int) -> nn.Sequential:
    return nn.Sequential(nn.LayerNorm(d_in), nn.Linear(d_in, d), nn.GELU(), nn.Linear(d, d_out))


@contextmanager
def hub_client(host: str | None):
    """Load from this host for the duration of a from_pretrained call (HF_ENDPOINT, e.g. hf-mirror.com).

    huggingface_hub builds its shared HTTP client once, from the proxy the environment names, and that client is
    never rebuilt; changing the endpoint alone leaves the proxy applied. Clearing the proxy variables while this
    runs makes the endpoint mean what it says.
    """
    keys = ("HF_ENDPOINT", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "all_proxy", "no_proxy")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        if host:
            os.environ["HF_ENDPOINT"] = host
            for k in keys[1:]:
                os.environ[k] = ""
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class MatrixModel(nn.Module):
    """path is a start point or a directory written by save().

    Two kinds of start point, by what the directory holds:
      matrix_config.json   a model save() wrote: that model is resumed, weights and all;
      anything else        a plain pretrained encoder (a directory, or an HF id such as jhu-clsp/mmBERT-base): the
                           encoder is loaded with AutoModel/AutoTokenizer and every head, the refining transformer
                           and the kind embedding, is initialised from scratch, so nothing is inherited from another
                           decision model.
    """

    def __init__(
        self,
        path: str,
        max_length: int = 2048,
        constraint_tokens: int = 64,
        action_tokens: int = 160,
        head_layers: int = 2,
        dropout: float = 0.1,
        hf_endpoint: str | None = None
    ):
        super().__init__()
        config_file = Path(path) / CONFIG_FILE
        if config_file.exists():
            config = json.loads(config_file.read_text(encoding="utf-8"))
            self.tokenizer = AutoTokenizer.from_pretrained(Path(path) / "tokenizer")
            self.encoder = AutoModel.from_pretrained(Path(path) / "encoder", attn_implementation="sdpa")
        else:
            config = {"base": str(path), "base_pretrained": True, "hf_endpoint": hf_endpoint,
                      "max_length": max_length, "constraint_tokens": constraint_tokens,
                      "action_tokens": action_tokens, "head_layers": head_layers, "levels": LEVELS}
            with hub_client(hf_endpoint):
                self.tokenizer = AutoTokenizer.from_pretrained(path)
                self.encoder = AutoModel.from_pretrained(path, attn_implementation="sdpa")
        self.config = config
        d = self.encoder.config.hidden_size
        layer = nn.TransformerEncoderLayer(d, max(1, d // 64), 4 * d, dropout, batch_first=True, norm_first=True)
        self.head = nn.TransformerEncoder(layer, config["head_layers"], enable_nested_tensor=False)
        self.kind_emb = nn.Embedding(len(KINDS), d)
        nn.init.zeros_(self.kind_emb.weight)
        n_levels = len(next(iter(config["levels"].values())))
        self.goal_head = mlp(d, d, n_levels)
        self.constraint_head = mlp(3 * d, d, 1)
        self.selection_head = mlp(d, d, 1)
        # Fitted on val after training, one per task; inference divides the logits by them
        self.register_buffer("temperature", torch.ones(len(TASKS)))
        self.checkpointing = False

        heads_file = Path(path) / HEADS_FILE
        if heads_file.exists():
            self.load_state_dict(torch.load(heads_file, map_location="cpu", weights_only=True), strict=False)

    # ------------------------------------------------------------------------------------- encoding

    def encode(
        self,
        problem: Problem,
        actions: list[Action]
    ) -> dict:
        """Token ids, the kind of every token, and the [MASK] positions of constraints and actions."""
        tok, cfg = self.tokenizer, self.config

        def ids(text: str, limit: int | None = None) -> list[int]:
            kwargs = {"truncation": True, "max_length": limit} if limit else {}
            return tok(text.replace(tok.mask_token, " "), add_special_tokens=False, **kwargs)["input_ids"]

        input_ids = [tok.cls_token_id] + ids(f"goal: {problem.goal}", 128) + [tok.sep_token_id]
        kinds = [KINDS["other"]] * len(input_ids)
        positions = {"constraint": [], "action": []}

        def block(kind: str, texts: list[str], limit: int):
            for text in texts:
                positions[kind].append(len(input_ids))
                part = [tok.mask_token_id] + ids(text, limit)
                input_ids.extend(part)
                kinds.extend([KINDS[kind]] * len(part))
            input_ids.append(tok.sep_token_id)
            kinds.append(KINDS["other"])

        block("constraint", [f" constraint ({'hard' if c.hard else 'preference'}) {c.id}: {c.text}"
                             for c in problem.constraints], cfg["constraint_tokens"])
        block("action", [f" action {a.id}: {a.description}" for a in actions], cfg["action_tokens"])
        room = cfg["max_length"] - len(input_ids) - 1
        if room < 0:
            raise ValueError(f"{len(actions)} actions and {len(problem.constraints)} constraints exceed max_length")
        state = ids("state: " + json.dumps(problem.state.data, ensure_ascii=False))[:room]
        input_ids += state + [tok.sep_token_id]
        kinds += [KINDS["other"]] * (len(state) + 1)
        return {"input_ids": input_ids, "kinds": kinds,
                "constraint_pos": positions["constraint"], "action_pos": positions["action"]}

    def collate(
        self,
        encoded: list[dict]
    ) -> dict[str, torch.Tensor]:
        length = max(len(e["input_ids"]) for e in encoded)
        n = max(len(e["action_pos"]) for e in encoded)
        m = max(1, max(len(e["constraint_pos"]) for e in encoded))
        batch = {
            "input_ids": torch.full((len(encoded), length), self.tokenizer.pad_token_id, dtype=torch.long),
            "attention_mask": torch.zeros((len(encoded), length), dtype=torch.long),
            "kinds": torch.zeros((len(encoded), length), dtype=torch.long),
            "action_pos": torch.zeros((len(encoded), n), dtype=torch.long),
            "action_mask": torch.zeros((len(encoded), n), dtype=torch.bool),
            "constraint_pos": torch.zeros((len(encoded), m), dtype=torch.long),
            "constraint_mask": torch.zeros((len(encoded), m), dtype=torch.bool),
        }
        for i, e in enumerate(encoded):
            k = len(e["input_ids"])
            batch["input_ids"][i, :k] = torch.tensor(e["input_ids"])
            batch["attention_mask"][i, :k] = 1
            batch["kinds"][i, :k] = torch.tensor(e["kinds"])
            for kind in ("action", "constraint"):
                pos = e[f"{kind}_pos"]
                batch[f"{kind}_pos"][i, :len(pos)] = torch.tensor(pos, dtype=torch.long)
                batch[f"{kind}_mask"][i, :len(pos)] = True
        return batch

    # -------------------------------------------------------------------------------------- forward

    def forward(
        self,
        batch: dict[str, torch.Tensor]
    ) -> dict[str, torch.Tensor]:
        """Raw logits: goal (B, N, levels), constraints (B, N, M), selection (B, N) with padding at -1e4."""
        device = self.temperature.device
        batch = {k: v.to(device) for k, v in batch.items()}
        h = self.encoder(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"]).last_hidden_state
        h = h + self.kind_emb(batch["kinds"])
        pad = ~batch["attention_mask"].bool()
        for layer in self.head.layers:
            if self.checkpointing and self.training and torch.is_grad_enabled():
                h = checkpoint(layer, h, src_key_padding_mask=pad, use_reentrant=False)
            else:
                h = layer(h, src_key_padding_mask=pad)

        def gather(pos: torch.Tensor) -> torch.Tensor:
            return torch.gather(h, 1, pos[:, :, None].expand(-1, -1, h.size(-1)))

        a, c = gather(batch["action_pos"]), gather(batch["constraint_pos"])
        n, m = a.size(1), c.size(1)
        ae, ce = a[:, :, None, :].expand(-1, -1, m, -1), c[:, None, :, :].expand(-1, n, -1, -1)
        selection = self.selection_head(a).squeeze(-1).float()
        return {
            "goal": self.goal_head(a).float(),
            "constraints": self.constraint_head(torch.cat([ae, ce, ae * ce], -1)).squeeze(-1).float(),
            "selection": selection.masked_fill(~batch["action_mask"], -1e4),
        }

    @torch.no_grad()
    def probabilities(
        self,
        batch: dict[str, torch.Tensor]
    ) -> dict[str, torch.Tensor]:
        """Calibrated outputs: goal distributions, P(violation), and the selection distribution."""
        logits = self(batch)
        t_goal, t_constraints, t_selection = self.temperature
        return {
            "goal": torch.softmax(logits["goal"] / t_goal, -1),
            "constraints": torch.sigmoid(logits["constraints"] / t_constraints),
            "selection": torch.softmax(logits["selection"] / t_selection, -1),
        }

    def save(
        self,
        path: str | Path
    ):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        self.tokenizer.save_pretrained(path / "tokenizer")
        self.encoder.save_pretrained(path / "encoder")
        torch.save({k: v for k, v in self.state_dict().items() if not k.startswith("encoder.")}, path / HEADS_FILE)
        (path / CONFIG_FILE).write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
