"""Does any benchmark test text appear in the data the model was trained or calibrated on?

Checks every JSONL file under the given training directories for: test case ids, every string in a
test state or question that is at least MIN_CHARS long (exact substring), and word 13-grams of the
test states (the usual contamination window).
"""
import json
import re
from pathlib import Path

MIN_CHARS = 25
NGRAM = 13


def strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def ngrams(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[i:i + NGRAM]) for i in range(len(words) - NGRAM + 1)}


def check(
    cases,
    training_dirs: list[str]
) -> dict:
    files = sorted(p for d in training_dirs for p in Path(d).rglob("*.jsonl"))
    if not files:
        return {"checked": False, "reason": f"no JSONL files under {training_dirs}"}
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in files)
    lowered = corpus.lower()
    train_grams = ngrams(corpus)
    cjk = len(re.findall(r"[一-鿿]", corpus))
    latin = len(re.findall(r"[A-Za-z]", corpus))

    id_hits = [c.id for c in cases if c.id in corpus]
    texts = {s for c in cases for s in strings(c.state) + strings(c.questions) if len(s) >= MIN_CHARS}
    text_hits = sorted(s for s in texts if s.lower() in lowered)
    test_grams = set().union(*(ngrams(" ".join(strings(c.state))) for c in cases))
    gram_hits = test_grams & train_grams
    return {
        "checked": True,
        "training_files": [str(p) for p in files],
        "case_id_hits": id_hits,
        "long_strings_checked": len(texts),
        "long_string_hits": text_hits[:20],
        "n_long_string_hits": len(text_hits),
        "state_13grams_checked": len(test_grams),
        "state_13gram_hits": len(gram_hits),
        "training_cjk_chars": cjk,
        "training_latin_letters": latin,
        "clean": not id_hits and not text_hits and not gram_hits,
    }
