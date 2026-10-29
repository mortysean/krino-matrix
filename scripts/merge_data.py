"""Merge generated Krino Matrix cases into a target dataset, keeping every case's own split.

    python scripts/merge_data.py --source data/krino_matrix/zh_generated --target data/krino_matrix/zh

Cases are deduplicated by id; ids already present in the target are skipped, so rerunning is safe.
Every case is validated through MatrixCase before it is written, and the target is rewritten atomically
per split file. Prints the counts before and after.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from krino.matrix import SPLITS, load


def main(args: argparse.Namespace) -> None:
    source, target = Path(args.source), Path(args.target)
    incoming = {}
    for name in SPLITS:
        path = source / f"{name}.jsonl"
        if path.exists():
            incoming[name] = load(path)

    existing = {}
    for name in SPLITS:
        path = target / f"{name}.jsonl"
        existing[name] = load(path) if path.exists() else []

    before = {name: len(cases) for name, cases in existing.items()}
    seen = {case.id for cases in existing.values() for case in cases}
    added = {}
    for name in SPLITS:
        fresh = [case for case in incoming.get(name, []) if case.id not in seen]
        for case in fresh:
            seen.add(case.id)
        added[name] = fresh

    for name in SPLITS:
        if not added[name]:
            continue
        path = target / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.writelines(case.model_dump_json() + "\n" for case in existing[name] + added[name])
        tmp.replace(path)

    print(f"source {source}")
    for name in SPLITS:
        total = before[name] + len(added[name])
        if before[name] or added[name]:
            print(f"  {name}: {before[name]} + {len(added[name])} = {total}")
    print(f"total: {sum(before.values())} + {sum(len(v) for v in added.values())} = {sum(before.values()) + sum(len(v) for v in added.values())}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="directory with train/val/test.jsonl to take cases from")
    parser.add_argument("--target", required=True, help="directory to merge into, in place")
    main(parser.parse_args())
