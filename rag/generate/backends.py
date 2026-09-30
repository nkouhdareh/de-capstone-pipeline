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

GroqBackend runs a hosted model on Groq's free plan: openai/gpt-oss-120b,
OpenAI's open-weight model (US), about forty times the local model's size. The
first choice was llama-3.3-70b-versatile, the local model's own family, but a
free account has no access to it (404, model_not_found), whatever the
documentation lists: the models an account can use come from its own
/models list. gpt-oss reasons before it answers; the reasoning is asked to be
brief and left out of the reply, and the token budget leaves room for it.
The backend needs a key in the environment, GROQ_API_KEY, which lives in the
git-ignored .env and nowhere else. Two more things learned by measuring:
- Groq answers Python's default user agent with 403 "error code: 1010", so
  every request names its own.
- A free plan limits tokens per minute and per day. A 429 reply says how long
  to wait. A short wait is served and the request tried again, so a long run
  survives the per-minute limit; a wait over MAX_WAIT means the daily limit,
  and the backend stops with that message instead of sleeping for hours. The
  evaluation is resumable, so the run carries on the next day.

Standard library only (urllib), so nothing new is installed.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NamedTuple, Protocol

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2:3b"
CONTEXT = 4096          # five chunks of up to 480 tokens, plus headers and the question
TIMEOUT = 600

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_KEY = "GROQ_API_KEY"               # the NAME of the environment variable, not a key
USER_AGENT = "de-capstone-rag/1.0"
MAX_ANSWER_TOKENS = 1500    # the answer, plus the model's own brief reasoning
RETRIES = 6
DEFAULT_WAIT = 20.0
MAX_WAIT = 120.0
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Generation(NamedTuple):
    text: str
    seconds: float
    prompt_tokens: int
    answer_tokens: int
    backend: str


class Backend(Protocol):
    name: str

    def generate(self, system: str, user: str) -> Generation: ...


class RateLimited(Exception):
    """The server asked us to slow down; wait this many seconds and try again."""

    def __init__(self, wait: float):
        super().__init__(f"rate limited, retry after {wait:.0f}s")
        self.wait = wait


def post_json(url: str, body: dict, headers: Mapping[str, str] | None = None,
              timeout: float = TIMEOUT) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise RateLimited(float(error.headers.get("retry-after") or DEFAULT_WAIT)) from None
        raise RuntimeError(f"{url} answered {error.code}: {error.read()[:300].decode('utf-8', 'replace')}") from None


def read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """NAME=value lines of a .env file. No new dependency for one small job."""
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, found, value = line.strip().partition("=")
            if found and name and not name.startswith("#"):
                values[name.strip()] = value.strip().strip("'\"")
    return values


class OllamaBackend:
    def __init__(self, model: str = OLLAMA_MODEL, url: str = OLLAMA_URL,
                 post: Callable[..., dict] = post_json):
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


class GroqBackend:
    """credential is the Groq key itself; left out, it is read from the
    environment, then from .env. It is sent only in the Authorization header."""

    def __init__(self, model: str = GROQ_MODEL, credential: str | None = None, url: str = GROQ_URL,
                 post: Callable[..., dict] = post_json, sleep: Callable[[float], None] = time.sleep):
        credential = credential or os.environ.get(GROQ_KEY) or read_env_file().get(GROQ_KEY)
        if not credential:
            raise RuntimeError(f"{GROQ_KEY} is not set: add it to {ENV_FILE}")
        self.model, self.url, self.post, self.sleep = model, url, post, sleep
        self.headers = {"Authorization": f"Bearer {credential}"}
        self.name = f"groq/{model}"

    def generate(self, system: str, user: str) -> Generation:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "seed": 0,
            "max_completion_tokens": MAX_ANSWER_TOKENS,
            "reasoning_effort": "low",
            "include_reasoning": False,
        }
        started = time.perf_counter()
        for attempt in range(RETRIES):
            try:
                reply = self.post(self.url, body, self.headers)
                break
            except RateLimited as limited:
                if limited.wait > MAX_WAIT:
                    raise RuntimeError(f"{self.name} asks to wait {limited.wait / 60:.0f} minutes: the "
                                       "free plan's limit is used up. Run again later.") from None
                if attempt == RETRIES - 1:
                    raise
                self.sleep(limited.wait + 1)
        usage = reply.get("usage", {})
        text = (reply["choices"][0]["message"].get("content") or "").strip()
        if not text:
            raise RuntimeError(f"{self.name} returned no answer text (finish reason: "
                               f"{reply['choices'][0].get('finish_reason')})")
        return Generation(text, time.perf_counter() - started,
                          usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), self.name)


def make_backend(name: str) -> Backend:
    if name == "ollama":
        return OllamaBackend()
    if name == "groq":
        return GroqBackend()
    raise ValueError(f"unknown backend {name!r}")


class LazyBackend:
    """Builds the real backend the first time an answer is generated. A question
    the guardrail refuses never reaches a model, so it should need neither a key
    nor a running server."""

    def __init__(self, name: str):
        self.name, self.real = name, None

    def generate(self, system: str, user: str) -> Generation:
        if self.real is None:
            self.real = make_backend(self.name)
        return self.real.generate(system, user)
