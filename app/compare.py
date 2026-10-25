"""Compare grouping models on the hand-labelled gold set (G-3). Zero-shot: nothing is trained here.

Run with:  python -m app.compare                                   (all methods)
           python -m app.compare --methods minilm tfidf bge_reranker

Each method scores every labelled gold pair (unsure pairs left out). Reported per method:
  AUC same    how well the score separates same_story pairs from the rest
              (0.5 = coin flip, 1.0 = perfect; needs no threshold)
  AUC linked  the same for same_story + follow_up against the rest
  best F1     F1 for same_story at the best threshold, and that threshold
              (picked on the gold set itself, so a little optimistic)
  ms/pair     on this machine, including model loading
Per-pair scores go to logs/compare_<date>.jsonl for error analysis.

Methods (D-024): minilm = cosine of the old MiniLM embeddings (grouping before D-024); tfidf = shared
words weighted by rarity; bge_m3, nemotron_embed = two-tower models (cosine of their embeddings);
bge_reranker, nemotron_rerank = cross-encoders (read both articles together); llm = the local Qwen3-4B
as judge (app/judge.py).
Transformer models run one at a time on the GPU in float16; the LLM is unloaded from the GPU first.
"""

import argparse
import json
import math
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import torch
from fastembed import TextEmbedding

from app import models, ollama
from app.db import connect
from app.judge import judge

ROOT = Path(__file__).resolve().parent.parent

PAIRS_SQL = """
    SELECT g.id, g.label, g.stratum,
           a.title, a.snippet, a.source_name, a.published_at,
           b.title, b.snippet, b.source_name, b.published_at
    FROM gold_pairs g JOIN articles a ON a.id = g.article_a JOIN articles b ON b.id = g.article_b
    WHERE g.label IS NOT NULL AND g.label <> 'unsure'
    ORDER BY g.id
"""

# The judge gives a label, not a score: rank the labels so AUC and thresholds still work.
JUDGE_SCORES = {"same_story": 1.0, "follow_up": 0.75, "same_actor": 0.5, "same_topic": 0.25, "unrelated": 0.0}


def load_pairs(conn) -> list[dict]:
    pairs = []
    for pair_id, label, stratum, *articles in conn.execute(PAIRS_SQL):
        a, b = ({"title": t, "snippet": s, "source": src, "date": d}
                for t, s, src, d in (articles[:4], articles[4:]))
        pairs.append({"id": pair_id, "label": label, "stratum": stratum, "a": a, "b": b})
    return pairs


def text(article: dict) -> str:
    return models.article_text(article["title"], article["snippet"])


def words(s: str) -> list[str]:
    return re.findall(r"\w{2,}", s.lower())


# ---------- methods: each takes the pairs and returns one score per pair ----------

def minilm(pairs: list[dict]) -> np.ndarray:
    model = TextEmbedding("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    texts = sorted({text(p[side]) for p in pairs for side in "ab"})
    vectors = np.array(list(model.embed(texts)))
    vectors = dict(zip(texts, vectors / np.linalg.norm(vectors, axis=1, keepdims=True)))
    return np.array([float(vectors[text(p["a"])] @ vectors[text(p["b"])]) for p in pairs])


def tfidf(pairs: list[dict]) -> np.ndarray:
    with connect() as conn:
        rows = conn.execute("SELECT title, snippet FROM articles").fetchall()
    df = Counter()
    for title, snippet in rows:
        df.update(set(words(f"{title} {snippet or ''}")))

    def vector(t: str) -> dict[str, float]:
        weights = {w: c * math.log(len(rows) / df[w]) for w, c in Counter(words(t)).items() if df[w]}
        norm = math.sqrt(sum(x * x for x in weights.values())) or 1.0
        return {w: x / norm for w, x in weights.items()}

    scores = []
    for p in pairs:
        va, vb = vector(text(p["a"])), vector(text(p["b"]))
        scores.append(sum(x * vb.get(w, 0.0) for w, x in va.items()))
    return np.array(scores)


def two_tower(name: str, pooling: str, prefix: str = "", trust: bool = False, dtype=torch.float32):
    def run(pairs: list[dict]) -> np.ndarray:
        texts = sorted({text(p[side]) for p in pairs for side in "ab"})
        vectors = dict(zip(texts, models.Embedder(name, pooling, prefix, trust, dtype).encode(texts)))
        return np.array([float(vectors[text(p["a"])] @ vectors[text(p["b"])]) for p in pairs])
    return run


def cross_encoder(name: str, template: str | None = None, trust: bool = False, dtype=torch.float32):
    def run(pairs: list[dict]) -> np.ndarray:
        texts = [(text(p["a"]), text(p["b"])) for p in pairs]
        scores = models.CrossEncoder(name, template, trust, dtype).score(texts + [(b, a) for a, b in texts])
        return (scores[:len(texts)] + scores[len(texts):]) / 2  # a link has no direction: average both orders
    return run


def llm(pairs: list[dict]) -> np.ndarray:
    scores = []
    with httpx.Client(timeout=600) as client:
        for p in pairs:
            label, _ = judge(client, *(f"{text(p[side])} ({p[side]['source']}, {p[side]['date']:%Y-%m-%d})"
                                       for side in "ab"))
            if label is None:
                print(f"  pair {p['id']}: unreadable answer, scored as unrelated")
            scores.append(JUDGE_SCORES.get(label, 0.0))
    return np.array(scores)


METHODS = {  # GPU transformers before the LLM, which is unloaded while they run
    "minilm": minilm,
    "tfidf": tfidf,
    "bge_m3": two_tower(models.EMBEDDER, pooling="cls"),
    # The ~1B NVIDIA models only fit the 4 GB GPU in float16.
    "nemotron_embed": two_tower("nvidia/llama-nemotron-embed-1b-v2", pooling="mean", prefix="passage: ", trust=True,
                                dtype=torch.float16),
    "bge_reranker": cross_encoder(models.CROSS_ENCODER),
    "smriti_ce": cross_encoder(str(models.FINE_TUNED)),  # bge_reranker fine-tuned on the LLM's labels (app/train.py)
    "nemotron_rerank": cross_encoder("nvidia/llama-nemotron-rerank-1b-v2",
                                     template="question:{a} \n \n passage:{b}", trust=True, dtype=torch.float16),
    "llm": llm,
}


# ---------- metrics ----------

def auc(scores: np.ndarray, positive: np.ndarray) -> float:
    """Chance that a random positive pair scores above a random negative one (ties count half)."""
    pos, neg = scores[positive], scores[~positive]
    if not len(pos) or not len(neg):
        return float("nan")
    diff = pos[:, None] - neg[None, :]
    return float((diff > 0).mean() + 0.5 * (diff == 0).mean())


def best_f1(scores: np.ndarray, positive: np.ndarray) -> tuple[float, float]:
    """Highest F1 over all thresholds (score >= threshold means positive), and that threshold."""
    best = (0.0, float("nan"))
    for threshold in np.unique(scores):
        predicted = scores >= threshold
        tp = int((predicted & positive).sum())
        if tp:
            precision, recall = tp / predicted.sum(), tp / positive.sum()
            best = max(best, (2 * precision * recall / (precision + recall), float(threshold)))
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--methods", nargs="+", choices=list(METHODS), default=list(METHODS))
    args = parser.parse_args()

    with connect() as conn:
        pairs = load_pairs(conn)
    if not pairs:
        print("No labelled gold pairs yet. Label some first: python -m app.gold --label")
        return
    labels = np.array([p["label"] for p in pairs])
    same = labels == "same_story"
    linked = same | (labels == "follow_up")
    print(f"{len(pairs)} labelled pairs: {same.sum()} same_story, {(linked & ~same).sum()} follow_up, "
          f"{(~linked).sum()} other. Device: {models.DEVICE}\n")

    with httpx.Client(timeout=30) as client:
        ollama.unload(client, ollama.MODEL)  # its 2.7 GB of VRAM would not leave room for the transformers

    print(f"{'method':16} {'AUC same':>9} {'AUC linked':>11} {'best F1':>8} {'threshold':>10} {'ms/pair':>8}")
    results = {}
    for name in args.methods:
        start = time.monotonic()
        scores = METHODS[name](pairs)
        ms = 1000 * (time.monotonic() - start) / len(pairs)
        models.free_gpu()
        results[name] = scores
        f1, threshold = best_f1(scores, same)
        print(f"{name:16} {auc(scores, same):>9.3f} {auc(scores, linked):>11.3f} {f1:>8.3f} "
              f"{threshold:>10.3f} {ms:>8.0f}", flush=True)

    out_file = ROOT / "logs" / f"compare_{date.today()}.jsonl"
    with out_file.open("w") as out:
        for i, p in enumerate(pairs):
            out.write(json.dumps({"pair_id": p["id"], "label": p["label"], "stratum": p["stratum"],
                                  **{name: round(float(s[i]), 4) for name, s in results.items()}}) + "\n")
    print(f"\nPer-pair scores: {out_file}")


if __name__ == "__main__":
    main()
