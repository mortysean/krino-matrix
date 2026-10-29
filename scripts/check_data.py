"""Check the zh and en Krino Matrix datasets before joint training, and print how far they have converged.

    python scripts/check_data.py --data data/krino_matrix

Exits non-zero when a hard check fails: duplicate ids, a group or id straddling two splits, a missing goal or
best label, a split field that disagrees with the file, or a constraint label naming an unknown action or
constraint. Structure densities are reported for comparison, not enforced.
"""
import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from krino.matrix import SPLITS, load

PROPORTIONS = {"train": 0.75, "val": 0.1, "test": 0.15}


def check_lang(root: Path, lang: str) -> tuple[dict, list[str]]:
    per = {name: load(root / lang / f"{name}.jsonl") for name in SPLITS if (root / lang / f"{name}.jsonl").exists()}
    cases = [c for name in SPLITS for c in per.get(name, [])]
    problems = []

    ids = [c.id for c in cases]
    dup = [k for k, v in collections.Counter(ids).items() if v > 1]
    if dup:
        problems.append(f"{lang}: {len(dup)} duplicate ids, e.g. {dup[:3]}")

    for name, cs in per.items():
        wrong = [c.id for c in cs if c.split != name]
        if wrong:
            problems.append(f"{lang}/{name}: {len(wrong)} cases whose split field disagrees with the file")

    groups = {name: {c.group for c in cs} for name, cs in per.items()}
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        shared = groups.get(a, set()) & groups.get(b, set())
        if shared:
            problems.append(f"{lang}: {len(shared)} groups straddle {a} and {b}")

    no_goal = [c.id for c in cases if len(c.labels.goal) != len(c.action_space)]
    if no_goal:
        problems.append(f"{lang}: {len(no_goal)} cases lack a goal label for every action")
    no_best = [c.id for c in cases if not c.labels.best]
    if no_best:
        problems.append(f"{lang}: {len(no_best)} cases lack a best label")

    bad_cons = []
    for c in cases:
        actions = {a.id for a in c.action_space}
        constraints = {x.id for x in c.constraints}
        for a, per_c in c.labels.constraints.items():
            if a not in actions or not set(per_c) <= constraints:
                bad_cons.append(c.id)
                break
    if bad_cons:
        problems.append(f"{lang}: {len(bad_cons)} cases have constraint labels for unknown actions/constraints")

    n = len(cases)
    goals = np.array([d for c in cases for d in c.labels.goal.values()]) if cases else np.zeros((0, 5))
    expected = (goals * np.arange(goals.shape[1])).sum(1) if len(goals) else np.zeros(0)
    stats = {
        "cases": n,
        "splits": {name: len(cs) for name, cs in per.items()},
        "splits_pct": {name: len(cs) / n for name, cs in per.items()} if n else {},
        "actions_per_case": float(np.mean([len(c.action_space) for c in cases])) if cases else 0.0,
        "constraints_per_case": float(np.mean([len(c.constraints) for c in cases])) if cases else 0.0,
        "hard_per_case": float(np.mean([sum(1 for x in c.constraints if x.hard) for c in cases])) if cases else 0.0,
        "with_constraints_pct": float(np.mean([1 if c.constraints else 0 for c in cases])) if cases else 0.0,
        "state_keys": float(np.mean([len(c.state) for c in cases])) if cases else 0.0,
        "goal_expected_mean": float(expected.mean()) if len(expected) else 0.0,
        "goal_low_share": float((expected < 1).mean()) if len(expected) else 0.0,
        "goal_max_p_mean": float(goals.max(1).mean()) if len(goals) else 0.0,
        "best_sharpness": float(np.mean([max(c.labels.best.values()) for c in cases if c.labels.best])) if cases else 0.0,
        "constraint_pairs": int(sum(len(v) for c in cases for v in c.labels.constraints.values())),
        "goal_action_agree": _agreement(cases),
        "unique_action_ids": len({a.id for c in cases for a in c.action_space}),
        "unified_pct": float(np.mean([1 if c.meta.get("unified") else 0 for c in cases])) if cases else 0.0,
    }
    return stats, problems


def _agreement(cases) -> float:
    """Share of cases where the action with the highest best label is also the one with the highest expected goal."""
    hits = total = 0
    for c in cases:
        if not c.labels.best:
            continue
        ids = [i for i in c.labels.best if i in c.labels.goal]
        if not ids:
            continue
        pick = max(ids, key=lambda k: c.labels.best[k])
        top = max(ids, key=lambda k: (np.array(c.labels.goal[k]) * np.arange(len(c.labels.goal[k]))).sum())
        hits += pick == top
        total += 1
    return hits / total if total else 0.0


def main(args: argparse.Namespace) -> int:
    root = Path(args.data)
    all_problems, results = [], {}
    for lang in args.langs:
        if not (root / lang).exists():
            all_problems.append(f"{lang}: missing")
            continue
        stats, problems = check_lang(root, lang)
        results[lang] = stats
        all_problems += problems

    rows = [
        ("cases", "cases", "{:.0f}"),
        ("splits", "split 条数", None),
        ("splits_pct", "split 比例", None),
        ("actions_per_case", "actions/case", "{:.2f}"),
        ("constraints_per_case", "constraints/case", "{:.2f}"),
        ("hard_per_case", "  其中 hard/case", "{:.2f}"),
        ("with_constraints_pct", "带约束的 case", "{:.1%}"),
        ("state_keys", "state 字段数", "{:.2f}"),
        ("goal_expected_mean", "goal 期望档位均值", "{:.2f}"),
        ("goal_low_share", "goal 落在低档(<1)占比", "{:.1%}"),
        ("goal_max_p_mean", "goal 最大概率均值", "{:.2f}"),
        ("best_sharpness", "best 峰值均值", "{:.2f}"),
        ("goal_action_agree", "best 与 goal 一致率", "{:.1%}"),
        ("constraint_pairs", "constraint 标签对", "{}"),
        ("unique_action_ids", "唯一 action id", "{}"),
        ("unified_pct", "已统一标记", "{:.1%}"),
    ]
    print(f"{'':34}" + "".join(f"{lang:>28}" for lang in results) + f"{'差异':>12}")
    for key, label, fmt in rows:
        cells, numeric = [], []
        for lang in results:
            value = results[lang][key]
            if fmt is None:
                if isinstance(value, dict):
                    cells.append(" ".join(f"{k}={v}" for k, v in value.items()))
                else:
                    cells.append(str(value))
            else:
                cells.append(fmt.format(value))
                if key != "cases":
                    numeric.append(float(value))
        gap = f"{max(numeric) / min(numeric):.1f}x" if len(numeric) == 2 and min(numeric) > 0 else ""
        print(f"{label:34}" + "".join(f"{c:>28}" for c in cells) + f"{gap:>12}")

    zh, en = results.get("zh"), results.get("en")
    if zh and en:
        print("\n比例核对:", " ".join(
            f"{lang} " + " ".join(f"{k}={v:.1%}" for k, v in results[lang]["splits_pct"].items()) for lang in results))
        print("目标比例:", " ".join(f"{k}={v:.0%}" for k, v in PROPORTIONS.items()))

    if all_problems:
        print("\n问题:")
        for problem in all_problems:
            print(f"  - {problem}")
        return 1
    print("\n全部硬性检查通过")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default="data/krino_matrix")
    parser.add_argument("--langs", nargs="+", default=["zh", "en"])
    sys.exit(main(parser.parse_args()))
