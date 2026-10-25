"""Calls to the local LLM through Ollama, shared by the scripts that use it."""

import logging
import time

import httpx

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen3:4b-instruct-2507-q4_K_M"  # D-017
NUM_GPU = 99            # force all layers onto the GPU; Ollama's own estimate leaves ~30% on CPU
# Under memory pressure Ollama turns mmap off, which puts the weights in RAM that can't be
# reclaimed and gets the service OOM-killed (I-007). systemd restarts it within seconds.
USE_MMAP = True
ATTEMPTS = 3
WAIT_SECONDS = 120

log = logging.getLogger("ollama")


def chat(client: httpx.Client, model: str, system: str, user: str, schema: dict, num_ctx: int) -> tuple[str, float]:
    """Model output (JSON matching `schema`) and seconds taken.

    Retried when Ollama dies mid-run (connection error or 5xx): waits for the restart first.
    """
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "think": False,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": num_ctx, "num_gpu": NUM_GPU, "use_mmap": USE_MMAP},
    }
    for attempt in range(1, ATTEMPTS):
        try:
            return _post(client, body)
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                raise
            log.warning("Ollama failed (%s), attempt %d/%d; waiting for it to come back",
                        type(e).__name__, attempt, ATTEMPTS)
            if not wait_for_ollama(client):
                raise
    return _post(client, body)


def _post(client: httpx.Client, body: dict) -> tuple[str, float]:
    start = time.monotonic()
    resp = client.post(f"{OLLAMA_URL}/api/chat", json=body)
    resp.raise_for_status()
    return resp.json()["message"]["content"], time.monotonic() - start


def wait_for_ollama(client: httpx.Client) -> bool:
    """Poll until Ollama answers again (after a crash and restart). False if it never does."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            client.get(OLLAMA_URL, timeout=5)
            return True
        except httpx.HTTPError:
            time.sleep(3)
    return False


def unload(client: httpx.Client, model: str) -> None:
    """Free the GPU memory the model holds, so other GPU work fits in the 4 GB."""
    try:
        client.post(f"{OLLAMA_URL}/api/generate", json={"model": model, "keep_alive": 0})
    except httpx.HTTPError as e:
        log.warning("could not unload %s: %s", model, e)
