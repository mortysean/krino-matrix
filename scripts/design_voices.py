"""按 app/tts/voices.py 里的描述，用 Qwen3-TTS VoiceDesign 生成每个角色的参考音频（data/models/voices/）。

在 krino_tts 环境里运行（scripts/world.sh voices 会帮你选好环境）：
    python scripts/design_voices.py               # 全部
    python scripts/design_voices.py dafeiyu-zh    # 只重做一个
    python scripts/design_voices.py --takes 4     # 每个音色生成 4 个候选，挑一个最像的（默认 1 个）

同一段描述每次生成的声音会有差别。用 --takes 生成几个候选（dafeiyu-zh.take1.wav …），试听后把满意的那个
改名成 dafeiyu-zh.wav 即可；语音服务只用不带 take 的那个。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import soundfile as sf
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "tts"))
from voices import VOICES  # noqa: E402

MODEL = ROOT / "data" / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
OUT = ROOT / "data" / "models" / "voices"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="音色名，默认全部")
    ap.add_argument("--takes", type=int, default=1)
    args = ap.parse_args()
    names = args.names or list(VOICES)
    from qwen_tts import Qwen3TTSModel

    model = Qwen3TTSModel.from_pretrained(str(MODEL), device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
    OUT.mkdir(parents=True, exist_ok=True)
    for name in names:
        v = VOICES[name]
        for i in range(1, args.takes + 1):
            wavs, sr = model.generate_voice_design(text=v["text"], language=v["language"], instruct=v["instruct"])
            path = OUT / (f"{name}.wav" if args.takes == 1 else f"{name}.take{i}.wav")
            sf.write(path, wavs[0], sr)
            print(f"{path.name}  {len(wavs[0]) / sr:.1f}s")
        (OUT / f"{name}.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
