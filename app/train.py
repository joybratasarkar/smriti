"""Fine-tune the cross-encoder on the teacher's labels (G-5): do these two articles belong to the same story?

Run with:  python -m app.train

Starts from bge-reranker-v2-m3 (models.CROSS_ENCODER). Target: 1 if the LLM said same_story, else 0; both
orders of each pair are used. Only the top TRAIN_LAYERS transformer layers and the head are trained, in
float32, so it fits the 4 GB GPU. Pairs whose id ends in 0 (10%) are held out: AUC and accuracy against the
teacher's labels are printed before and after training. The model and those numbers (smriti.json) are saved
to models.FINE_TUNED, which app.group uses. The real test is the hand-labelled gold set (app.compare).
"""

import json
import logging
import random
import time
from datetime import datetime

import httpx
import numpy as np
import torch

from app import models, ollama
from app.compare import auc
from app.db import connect

EPOCHS = 2
TRAIN_LAYERS = 4
LEARNING_RATE = 2e-5
BATCH = 8           # with MAX_TOKENS, keeps training inside the 4 GB next to the 2.3 GB float32 model
MAX_TOKENS = 128    # title + snippet; longer snippets are cut

PAIRS_SQL = """
    SELECT t.id, t.label, a.title, a.snippet, b.title, b.snippet
    FROM train_pairs t JOIN articles a ON a.id = t.article_a JOIN articles b ON b.id = t.article_b
    WHERE t.label IS NOT NULL
"""

log = logging.getLogger("train")


def examples(rows) -> list[tuple[str, str, float]]:
    """(first text, second text, 1.0 if same story) in both orders: a link has no direction."""
    out = []
    for _, label, title_a, snippet_a, title_b, snippet_b in rows:
        a, b = models.article_text(title_a, snippet_a), models.article_text(title_b, snippet_b)
        y = float(label == "same_story")
        out += [(a, b, y), (b, a, y)]
    return out


def evaluate(cross_encoder: models.CrossEncoder, held: list[tuple[str, str, float]]) -> dict:
    scores = cross_encoder.score([(a, b) for a, b, _ in held])
    same = np.array([y == 1.0 for *_, y in held])
    return {"auc": round(auc(scores, same), 3), "accuracy_at_0.5": round(float(np.mean((scores >= 0.5) == same)), 3)}


def train_epoch(cross_encoder: models.CrossEncoder, train: list, optimizer, rng: random.Random) -> float:
    cross_encoder.model.train()
    rng.shuffle(train)
    total = 0.0
    for i in range(0, len(train), BATCH):
        chunk = train[i:i + BATCH]
        batch = cross_encoder.tokenizer([a for a, _, _ in chunk], [b for _, b, _ in chunk], padding=True,
                                        truncation="longest_first", max_length=MAX_TOKENS,
                                        return_tensors="pt").to(models.DEVICE)
        target = torch.tensor([y for *_, y in chunk], dtype=torch.float32, device=models.DEVICE)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(cross_encoder.model(**batch).logits.view(-1), target)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        total += loss.item() * len(chunk)
        if (i // BATCH) % 100 == 0:
            log.info("  %d / %d examples, loss %.3f", i + len(chunk), len(train), loss.item())
    cross_encoder.model.eval()
    return total / len(train)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with connect() as conn:
        rows = conn.execute(PAIRS_SQL).fetchall()
    held = examples([r for r in rows if r[0] % 10 == 0])
    train = examples([r for r in rows if r[0] % 10 != 0])
    if not held or not train:
        raise SystemExit(f"Not enough labelled pairs ({len(rows)}). Run python -m app.teach --sample 3000 --label first.")
    log.info("%d labelled pairs: %d training and %d held-out examples (both orders); %.0f%% same story",
             len(rows), len(train), len(held), 100 * np.mean([y for *_, y in train]))

    with httpx.Client(timeout=30) as client:
        ollama.unload(client, ollama.MODEL)  # free the GPU for training
    cross_encoder = models.CrossEncoder()
    before = evaluate(cross_encoder, held)
    log.info("Before training (zero-shot), held out: %s", before)

    for param in cross_encoder.model.parameters():
        param.requires_grad = False
    trainable = [*cross_encoder.model.roberta.encoder.layer[-TRAIN_LAYERS:].parameters(),
                 *cross_encoder.model.classifier.parameters()]
    for param in trainable:
        param.requires_grad = True
    optimizer = torch.optim.AdamW(trainable, lr=LEARNING_RATE, weight_decay=0.01)

    rng, started = random.Random(42), time.time()
    for epoch in range(1, EPOCHS + 1):
        loss = train_epoch(cross_encoder, train, optimizer, rng)
        log.info("Epoch %d: mean loss %.3f, held out %s, %.0f min so far", epoch, loss,
                 evaluate(cross_encoder, held), (time.time() - started) / 60)
    after = evaluate(cross_encoder, held)
    if after["auc"] <= before["auc"]:
        raise SystemExit(f"Fine-tuning did not help on held-out pairs (before {before}, after {after}); not saved.")

    cross_encoder.model.save_pretrained(models.FINE_TUNED)
    cross_encoder.tokenizer.save_pretrained(models.FINE_TUNED)
    (models.FINE_TUNED / "smriti.json").write_text(json.dumps({
        "base": models.CROSS_ENCODER, "teacher": ollama.MODEL, "target": "same_story",
        "labelled_pairs": len(rows), "epochs": EPOCHS, "train_layers": TRAIN_LAYERS,
        "held_out_before": before, "held_out_after": after, "trained_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2))
    log.info("Saved to %s. Held out: before %s, after %s", models.FINE_TUNED, before, after)


if __name__ == "__main__":
    main()
