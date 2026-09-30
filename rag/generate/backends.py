"""Phase 6: the generators behind one small interface.

A backend takes the (system, user) messages from prompt.build_prompt and
returns a Generation. Anything else in the system talks to that interface
only, so a backend can be swapped without touching retrieval, the prompt or
the citation check, and every backend is measured the same way.

OllamaBackend runs a local model through Ollama's HTTP API, with no key and no
network: llama3.2:3b (Meta, US) by default, 2.0 GB. Temperature 0 and a fixed
seed make an answer repeatable. On this CPU (i5-1334U, measured 2026-09-30)
reading five chunks, about 2,200 tokens, takes about 53 s and writing a
120-token answer about 14 s, so a new question costs about a minute. Ollama
keeps the last prompt it read, so asking the same question again costs 16 s.

Standard library only (urllib), so nothing new is installed.
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from typing import NamedTuple, Protocol

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2:3b"
CONTEXT = 4096          # five chunks of up to 480 tokens, plus headers and the question
TIMEOUT = 600


class Generation(NamedTuple):
    text: str
    seconds: float
    prompt_tokens: int
    answer_tokens: int
    backend: str


class Backend(Protocol):
    name: str

    def generate(self, system: str, user: str) -> Generation: ...


def post_json(url: str, body: dict, timeout: float = TIMEOUT) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


class OllamaBackend:
    def __init__(self, model: str = OLLAMA_MODEL, url: str = OLLAMA_URL,
                 post: Callable[[str, dict], dict] = post_json):
        self.model, self.url, self.post = model, url, post
        self.name = f"ollama/{model}"

    def generate(self, system: str, user: str) -> Generation:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": 0, "seed": 0, "num_ctx": CONTEXT},
        }
        started = time.perf_counter()
        reply = self.post(self.url, body)
        return Generation(reply["message"]["content"].strip(), time.perf_counter() - started,
                          reply.get("prompt_eval_count", 0), reply.get("eval_count", 0), self.name)
