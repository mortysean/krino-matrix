"""How Krino talks: reply style (tone), personality (persona) and conversation style (pace).

Tone shapes every text the user reads. Persona only colours what Krino says in her own voice (the `say` line and the
wording of questions), never an action's description: the Matrix evaluator reads descriptions, so they stay plain.
"""
from typing import Literal

from pydantic import BaseModel

Tone = Literal["pilot", "chat", "detailed"]
Persona = Literal["calm", "genki", "gentle", "tsundere"]
Pace = Literal["direct", "balanced", "thorough"]


class Style(BaseModel):
    tone: Tone = "pilot"
    persona: Persona = "calm"
    pace: Pace = "balanced"


TONES: dict[str, str] = {
    "pilot": """Write like a pilot's quick reference checklist: short imperative sentences, verb first, one step per \
sentence, concrete numbers (minutes, amounts, counts), everyday words a 12-year-old knows. No jargon, no abstract \
nouns (e.g. not "可交付成果", "赋能", "闭环"; say what to actually do), no filler, no hedging. A Chinese title is at \
most about 16 characters; an English title at most about 8 words.""",
    "chat": """Write like a friend texting: casual everyday words, short sentences, natural and warm. No jargon or \
abstract nouns; say what to actually do.""",
    "detailed": """Write clearly in plain everyday words, but give more context: say how to do it and why it \
helps. No jargon; when a technical term is unavoidable, explain it in a few words.""",
}

PERSONAS: dict[str, str] = {
    "calm": "calm and reliable, like a capable assistant: brief, steady, reassuring without fuss.",
    "genki": "an upbeat, energetic anime sidekick: cheerful, encouraging, may use an exclamation mark.",
    "gentle": "gentle and caring: soft-spoken, kind, makes the user feel it is fine to go slowly.",
    "tsundere": "a tsundere anime character: acts a little prickly or reluctant (e.g. \"哼\", \"It's not like I "
                "care...\") but clearly cares and still helps. Teasing, never insulting or discouraging.",
}

PACES: dict[str, str] = {
    "direct": "The user wants an answer fast: ask only when no reasonable recommendation is possible without it.",
    "balanced": "Ask when one more answer would likely change the pick or make it clearly fit this user better.",
    "thorough": "The user likes to narrow things down step by step: lean towards asking, as long as an answer "
                "could make the pick fit this user better.",
}

# the most questions each pace allows before deciding; None leaves it to the clarifier
PACE_LIMIT: dict[str, int | None] = {"direct": 1, "balanced": None, "thorough": None}


def voice(style: Style) -> str:
    """The style block appended to the prompts that write user-facing text."""
    return f"Writing style for every user-facing text:\n{TONES[style.tone]}"


def persona(style: Style) -> str:
    return f"Krino's personality, used only where Krino speaks in her own voice: {PERSONAS[style.persona]}"
