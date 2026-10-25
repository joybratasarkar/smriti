"""Transformer models for grouping (D-024), on the GPU when there is one.

EMBEDDER is the two-tower model: one vector per article, compared by cosine.
CROSS_ENCODER reads two texts together and gives the probability that they belong together.
Both run in float32: on the GTX 1650, float16 matrix maths is about 5x slower (measured 2026-10-20).
The ~1B NVIDIA models only fit the 4 GB in float16, so they take it as a parameter.
Texts are batched in length order, so short headlines aren't padded to the length of long snippets.
"""

import gc
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer

EMBEDDER = "BAAI/bge-m3"                  # 568M, multilingual, 1024-dim (MIT)
CROSS_ENCODER = "BAAI/bge-reranker-v2-m3"  # 568M, multilingual (Apache-2.0)
DIMENSIONS = 1024
# CROSS_ENCODER fine-tuned on the LLM teacher's labels for "same story?" (app/train.py); used by app.group.
FINE_TUNED = Path(__file__).resolve().parent.parent / "models" / "ce-same-story"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BATCH = 16  # 32 long snippet pairs in float32 come close to filling the 4 GB
MAX_TOKENS = 512  # title + snippet is far shorter


def article_text(title: str, snippet: str | None) -> str:
    return f"{title}. {snippet}" if snippet else title


def load(model_class, name: str, trust: bool, dtype: torch.dtype):
    """Tokenizer and model. `trust` runs the model repo's own code (the NVIDIA models need it)."""
    tokenizer = AutoTokenizer.from_pretrained(name, trust_remote_code=trust)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = model_class.from_pretrained(name, dtype=dtype, trust_remote_code=trust)
    return tokenizer, model.to(DEVICE).eval()


def length_batches(texts: list) -> list[list[int]]:
    """Indexes of `texts` in batches of similar length (each item a string or a pair of strings)."""
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]) if isinstance(texts[i], str) else sum(map(len, texts[i])))
    return [order[i:i + BATCH] for i in range(0, len(order), BATCH)]


def free_gpu() -> None:
    """Release GPU memory of models that are no longer referenced."""
    gc.collect()
    if DEVICE == "cuda":
        torch.cuda.empty_cache()


class Embedder:
    def __init__(self, name: str = EMBEDDER, pooling: str = "cls", prefix: str = "", trust: bool = False,
                 dtype: torch.dtype = torch.float32):
        self.tokenizer, self.model = load(AutoModel, name, trust, dtype)
        self.pooling, self.prefix = pooling, prefix

    def encode(self, texts: list[str]) -> np.ndarray:
        """L2-normalized vectors (float32), so a dot product is the cosine."""
        out = np.zeros((len(texts), self.model.config.hidden_size), dtype=np.float32)
        with torch.inference_mode():
            for idx in length_batches(texts):
                batch = self.tokenizer([self.prefix + texts[i] for i in idx], padding=True, truncation=True,
                                       max_length=MAX_TOKENS, return_tensors="pt").to(DEVICE)
                hidden = self.model(**batch).last_hidden_state.float()
                if self.pooling == "cls":
                    vectors = hidden[:, 0]
                else:  # mean over real tokens, padding left out
                    mask = batch["attention_mask"].unsqueeze(-1).float()
                    vectors = (hidden * mask).sum(1) / mask.sum(1)
                out[idx] = torch.nn.functional.normalize(vectors, dim=-1).cpu().numpy()
        return out


class CrossEncoder:
    def __init__(self, name: str = CROSS_ENCODER, template: str | None = None, trust: bool = False,
                 dtype: torch.dtype = torch.float32):
        self.name = name
        self.tokenizer, self.model = load(AutoModelForSequenceClassification, name, trust, dtype)
        self.template = template  # some models expect one formatted sequence instead of a text pair

    def score(self, pairs: list[tuple[str, str]]) -> np.ndarray:
        """Probability (sigmoid of the logit) that each (first, second) pair belongs together."""
        out = np.zeros(len(pairs), dtype=np.float32)
        with torch.inference_mode():
            for idx in length_batches(pairs):
                chunk = [pairs[i] for i in idx]
                if self.template:
                    batch = self.tokenizer([self.template.format(a=a, b=b) for a, b in chunk], padding=True,
                                           truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
                else:  # a standard text pair: [CLS] a [SEP] b [SEP]
                    batch = self.tokenizer([a for a, _ in chunk], [b for _, b in chunk], padding=True,
                                           truncation="longest_first", max_length=MAX_TOKENS, return_tensors="pt")
                logits = self.model(**batch.to(DEVICE)).logits.float().view(-1)
                out[idx] = torch.sigmoid(logits).cpu().numpy()
        return out
