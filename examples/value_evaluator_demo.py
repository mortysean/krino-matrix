"""Try the value evaluator: fine-tune on a few hand-labeled samples, save, reload and score:

    python examples/value_evaluator_demo.py
    python examples/value_evaluator_demo.py data.jsonl      # train on your own samples (one Sample per line)

The first run downloads the backbone from Hugging Face. A few toy samples only show the plumbing;
real scores need a real labeled dataset.
"""
import sys
from pathlib import Path

# Make the project root importable when this file is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.schema import State, Action
from core.evaluator.value_evaluator import ValueModel, ValueEvaluator, Sample, load_samples, train

# Edit these to try your own scenario
BACKBONE = "BAAI/bge-small-zh-v1.5"
SAVE_DIR = "checkpoints/value_model"
EPOCHS = 10
STATE = State(data={"weather": "大雨", "distance_km": 8, "has_car": False})
OBJECTIVE = "30 分钟内到公司"
SAMPLES = [
    Sample(state=STATE, objective=OBJECTIVE, score=1.0,
           action=Action(id="take_taxi", description="打车去公司，雨天也不用淋雨，大约 20 分钟。")),
    Sample(state=STATE, objective=OBJECTIVE, score=0.6,
           action=Action(id="take_subway", description="步行到地铁站坐地铁，大约 35 分钟。")),
    Sample(state=STATE, objective=OBJECTIVE, score=0.0,
           action=Action(id="walk", description="冒雨步行 8 公里去公司。")),
]


if __name__ == "__main__":
    samples = load_samples(sys.argv[1]) if len(sys.argv) > 1 else SAMPLES
    evaluator = ValueEvaluator(ValueModel(BACKBONE))
    train(evaluator.model, samples, epochs=EPOCHS)
    evaluator.model.save(SAVE_DIR)

    evaluator = ValueEvaluator(ValueModel(SAVE_DIR))
    print(f"\nScores from {SAVE_DIR}:")
    for s in samples:
        score = evaluator.evaluate(s.state, s.objective, s.action)
        print(f"- {s.action.id}: {score:.3f} (label {s.score})")
