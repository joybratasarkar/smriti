"""The local LLM as judge: how are two news items (articles, or stories) connected?

Uses the same label rules as the hand-labelled gold set (MEANINGS in app/gold.py).
"""

import json

import httpx

from app import ollama
from app.gold import HARD_CASES, MEANINGS

LABELS = [label for label in MEANINGS if label != "unsure"]
RULES = (
    "You compare two news items and say how they are connected. An item is an article (title and snippet) "
    "or a story (its latest headlines).\n"
    "Pick the FIRST label that fits:\n"
    + "\n".join(f"- {label}: {MEANINGS[label]}" for label in LABELS)
    + "\nHard cases:\n" + "\n".join(f"- {case}" for case in HARD_CASES)
)
SYSTEM = RULES + (
    "\nThen give the reason in one short sentence: what the two items share, or don't.\n"
    "Use only what the texts say. Return JSON only."
)
SYSTEM_LABEL_ONLY = RULES + "\nUse only what the texts say. Return JSON only."  # faster: the reason is most of the output
SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": LABELS}, "reason": {"type": "string"}},
    "required": ["label", "reason"],
}
SCHEMA_LABEL_ONLY = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": LABELS}},
    "required": ["label"],
}


def judge(client: httpx.Client, first: str, second: str, reason: bool = True) -> tuple[str | None, str | None]:
    """(label, one-line reason or None) for two described items, or (None, None) if the answer can't be read."""
    raw, _ = ollama.chat(client, ollama.MODEL, SYSTEM if reason else SYSTEM_LABEL_ONLY,
                         f"Item A: {first}\n\nItem B: {second}", SCHEMA if reason else SCHEMA_LABEL_ONLY, num_ctx=2048)
    try:
        answer = json.loads(raw)
        return answer["label"], answer.get("reason")
    except (json.JSONDecodeError, KeyError, TypeError):
        return None, None
