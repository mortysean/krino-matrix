"""A Laya-style decision head (https://github.com/NandhaKishorM/laya), specialised to one typed question:
"how much value does this action bring toward the goal?", answered as a distribution over LEVELS.

Sequence: [CLS] score question: <instruction + goal + action> [SEP] [MASK] level 0 [MASK] level 1 ... [SEP] state [SEP]

The encoder reads the whole sequence in one forward pass, a small transformer head refines it, and the
hidden state at each level's [MASK] is scored into one logit, so the levels are read from their own text.
"""
import json
from pathlib import Path

import torch
from torch import nn
from transformers import AutoModel, AutoTokenizer

from ...schema import State, Action
from ...matrix import LEVELS as RUBRICS

DEFAULT_BACKBONE = "BAAI/bge-small-zh-v1.5"
HEAD_FILE = "head.pt"
CONFIG_FILE = "value_config.json"

INSTRUCTION = "How much value does this action bring toward the goal, given the state?"
# The value rubric of core.matrix; a saved model stores its own copy, so a trained one keeps reading the same text
LEVELS = RUBRICS["zh"]
LEVEL_TOKENS = 48       # cap per level text, as in Laya
TEMP_MIN, TEMP_MAX = 0.5, 5.0


def question_text(
    goal: str,
    action: Action
) -> str:
    return f"score question: {INSTRUCTION}\nGoal: {goal}\nAction: {action.id}\n{action.description}"


class ValueModel(nn.Module):
    """Encoder + Laya decision head: (state, goal, action) → logits over LEVELS in one forward pass.

    path is a Hugging Face backbone name, or a directory written by save(); the head is
    freshly initialized for a backbone and restored for a saved model.
    """

    def __init__(
        self,
        path: str = DEFAULT_BACKBONE,
        max_length: int = 512,
        head_max_length: int = 320,
        head_layers: int = 2,
        dropout: float = 0.1
    ):
        super().__init__()
        config_file = Path(path) / CONFIG_FILE
        config = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
        self.max_length = config.get("max_length", max_length)
        self.head_max_length = config.get("head_max_length", head_max_length)
        self.levels = config.get("levels", LEVELS)
        head_layers = config.get("head_layers", head_layers)

        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.encoder = AutoModel.from_pretrained(path)
        d = self.encoder.config.hidden_size
        layer = nn.TransformerEncoderLayer(d, max(1, d // 64), 4 * d, dropout, batch_first=True, norm_first=True)
        self.head = nn.TransformerEncoder(layer, head_layers, enable_nested_tensor=False)
        self.scorer = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
        self.register_buffer("temperature", torch.ones(()))      # fitted after training, see train.calibrate
        head_file = Path(path) / HEAD_FILE
        if head_file.exists():
            self.load_state_dict(torch.load(head_file, map_location="cpu", weights_only=True), strict=False)

    def encode(
        self,
        state: State,
        goal: str,
        action: Action
    ) -> tuple[list[int], list[int]]:
        """Token ids and the [MASK] position of each level. The state is cut to whatever room the head leaves."""
        tok = self.tokenizer

        def ids(text: str, **kwargs) -> list[int]:
            return tok(text.replace(tok.mask_token, " "), add_special_tokens=False, **kwargs)["input_ids"]

        options = [
            [tok.mask_token_id] + ids(f" level {i}: {text}", truncation=True, max_length=LEVEL_TOKENS)
            for i, text in enumerate(self.levels)
        ]
        budget = self.head_max_length - sum(len(o) for o in options)
        head = [tok.cls_token_id] + ids(question_text(goal, action))[:max(8, budget)] + [tok.sep_token_id]
        markers = []
        for option in options:
            markers.append(len(head))
            head += option
        head.append(tok.sep_token_id)
        room = max(0, self.max_length - len(head) - 1)
        state_ids = ids(json.dumps(state.data, ensure_ascii=False))[:room]
        return head + state_ids + [tok.sep_token_id], markers

    def forward(
        self,
        encoded: list[tuple[list[int], list[int]]]
    ) -> torch.Tensor:
        """Outputs of encode() → raw logits of shape (batch, len(levels)); divide by temperature for calibrated ones."""
        device = self.temperature.device
        length = max(len(ids) for ids, _ in encoded)
        input_ids = torch.full((len(encoded), length), self.tokenizer.pad_token_id, dtype=torch.long)
        attention_mask = torch.zeros_like(input_ids)
        for i, (ids, _) in enumerate(encoded):
            input_ids[i, :len(ids)] = torch.tensor(ids)
            attention_mask[i, :len(ids)] = 1
        markers = torch.tensor([m for _, m in encoded], device=device)
        input_ids, attention_mask = input_ids.to(device), attention_mask.to(device)

        h = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        h = self.head(h, src_key_padding_mask=~attention_mask.bool())
        h = torch.gather(h, 1, markers[:, :, None].expand(-1, -1, h.size(-1)))
        return self.scorer(h).squeeze(-1).float()

    @torch.no_grad()
    def probabilities(
        self,
        encoded: list[tuple[list[int], list[int]]]
    ) -> torch.Tensor:
        """Calibrated distribution over levels, shape (batch, len(levels))."""
        return torch.softmax(self(encoded) / self.temperature, -1)

    def save(
        self,
        path: str
    ):
        self.tokenizer.save_pretrained(path)
        self.encoder.save_pretrained(path)
        head = {k: v for k, v in self.state_dict().items() if not k.startswith("encoder.")}
        torch.save(head, Path(path) / HEAD_FILE)
        config = {
            "max_length": self.max_length,
            "head_max_length": self.head_max_length,
            "head_layers": len(self.head.layers),
            "levels": self.levels,
        }
        (Path(path) / CONFIG_FILE).write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def expected_value(probabilities: torch.Tensor) -> torch.Tensor:
    """The expected level, scaled to [0, 1]: the scalar an Evaluator returns."""
    levels = torch.arange(probabilities.size(-1), device=probabilities.device, dtype=probabilities.dtype)
    return (probabilities * levels).sum(-1) / (probabilities.size(-1) - 1)
