"""Train the value evaluator (a Laya-style decision head), calibrate, evaluate, save, reload and score:

    python examples/value_evaluator_demo.py                         # one hand-labeled toy case
    python examples/value_evaluator_demo.py data/krino_matrix/zh    # Krino Matrix train.jsonl / test.jsonl
    python examples/value_evaluator_demo.py data/krino_matrix/zh --epochs 8

The first run downloads the backbone from Hugging Face. The toy case only shows the plumbing;
real scores need real labeled cases.
"""
import argparse
import random
import sys
from pathlib import Path

# Make the project root importable when this file is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.schema import State, Constraint, Action
from core.matrix import MatrixCase, Labels, load
from core.evaluator.value_evaluator import ValueModel, ValueEvaluator, train, calibrate, evaluate

BACKBONE = "BAAI/bge-small-zh-v1.5"
SAVE_DIR = "checkpoints/value_model"
CALIB_FRACTION = 0.1        # of the training cases, held out before training to fit the temperature and pick epochs
TOY = [MatrixCase(
    id="toy",
    lang="zh",
    state={"weather": "大雨", "distance_km": 8, "has_car": False},
    goal="到公司",
    constraints=[Constraint(id="arrive_in_30_min", text="30 分钟内到", hard=True)],
    action_space=[
        Action(id="take_taxi", description="打车去公司，雨天也不用淋雨，大约 20 分钟。"),
        Action(id="take_subway", description="步行到地铁站坐地铁，大约 35 分钟。"),
        Action(id="walk", description="冒雨步行 8 公里去公司。"),
    ],
    # distributions over LEVELS: 有害或不可行 / 较差 / 一般 / 良好 / 优秀
    labels=Labels(goal={
        "take_taxi": [0.0, 0.0, 0.05, 0.25, 0.7],
        "take_subway": [0.0, 0.15, 0.6, 0.25, 0.0],
        "walk": [0.85, 0.15, 0.0, 0.0, 0.0],
    }),
)]


def show(name: str, metrics: dict):
    print(f"{name}: " + ", ".join(f"{k} {v:.3f}" if isinstance(v, float) else f"{k} {v}" for k, v in metrics.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data", nargs="?", help="directory with train.jsonl and test.jsonl; omit for the toy case")
    parser.add_argument("--epochs", type=int, default=None, help="default: 4 (Laya's), 30 for the toy case")
    parser.add_argument("--backbone", default=BACKBONE, help=f"Hugging Face encoder to start from; default: {BACKBONE}")
    parser.add_argument("--save", default=SAVE_DIR, help=f"where to save the trained model; default: {SAVE_DIR}")
    parser.add_argument("--freeze-encoder", action="store_true", help="train the decision head only")
    args = parser.parse_args()

    if args.data:
        cases = load(Path(args.data) / "train.jsonl")
        test = load(Path(args.data) / "test.jsonl")
        random.Random(0).shuffle(cases)
        n_calib = max(1, round(len(cases) * CALIB_FRACTION))
        calib, cases = cases[:n_calib], cases[n_calib:]
    else:
        cases = calib = test = TOY       # one case: nothing to hold out, so these numbers say nothing

    evaluator = ValueEvaluator(ValueModel(args.backbone))
    train(evaluator.model, cases, epochs=args.epochs or (4 if args.data else 30),
          micro_batch=8 if args.data else 3, grad_accum=8 if args.data else 1, freeze_encoder=args.freeze_encoder)
    print(f"temperature: {calibrate(evaluator.model, calib):.3f}")
    if args.data:
        show("val", evaluate(evaluator.model, calib))      # choose epochs on this, not on test
    show("test", evaluate(evaluator.model, test))
    evaluator.model.save(args.save)

    evaluator = ValueEvaluator(ValueModel(args.save))
    case = test[0]
    print(f"\nScores from {args.save} for: {case.goal}")
    state = State(data=case.state)
    for action in case.action_space:
        p = evaluator.distribution(state, case.goal, action)
        gold = case.labels.goal.get(action.id)
        print(f"- {action.id}: {evaluator.evaluate(state, case.goal, action):.3f}"
              f"  levels {[round(x, 2) for x in p]}  gold {gold}")
