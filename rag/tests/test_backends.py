"""Unit tests for the generator interface. Fake HTTP calls stand in for Ollama
and for Groq, so these need no server, no key and no network: CI runs them."""
import io

from rag.generate import backends
from rag.generate.backends import GroqBackend, OllamaBackend, RateLimited, read_env_file


class FakePost:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, url, body):
        self.calls.append((url, body))
        return self.reply


def test_ollama_sends_both_messages_at_temperature_zero_and_reads_the_reply():
    post = FakePost({"message": {"content": " Hypomagnesemia was reported [1]. "},
                     "prompt_eval_count": 2216, "eval_count": 9})
    backend = OllamaBackend(model="llama3.2:3b", post=post)

    generation = backend.generate("system text", "user text")

    url, body = post.calls[0]
    assert url.endswith("/api/chat")
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["options"]["temperature"] == 0 and body["stream"] is False
    assert generation.text == "Hypomagnesemia was reported [1]."
    assert (generation.prompt_tokens, generation.answer_tokens) == (2216, 9)
    assert generation.backend == "ollama/llama3.2:3b"


# The hosted backend. No request ever leaves the test: FakeGroq answers.

GROQ_REPLY = {"choices": [{"message": {"content": " Hypomagnesemia was reported [1]. "}}],
              "usage": {"prompt_tokens": 2300, "completion_tokens": 12}}


class FakeGroq:
    """Answers with the given replies in order; a RateLimited reply is raised."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, body, headers):
        self.calls.append((url, body, headers))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_groq_sends_the_credential_only_in_the_header_and_reads_the_reply():
    post = FakeGroq([GROQ_REPLY])
    backend = GroqBackend(credential="dummy-credential", post=post)

    generation = backend.generate("system text", "user text")

    _, body, headers = post.calls[0]
    assert headers == {"Authorization": "Bearer dummy-credential"}
    assert "dummy-credential" not in str(body)
    assert body["temperature"] == 0 and body["model"] == "openai/gpt-oss-120b"
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    assert generation.text == "Hypomagnesemia was reported [1]."
    assert (generation.prompt_tokens, generation.answer_tokens) == (2300, 12)
    assert generation.backend == "groq/openai/gpt-oss-120b"


def test_groq_with_an_empty_reply_stops_instead_of_saving_an_empty_answer():
    """A reasoning model can spend its whole budget thinking and return no text."""
    empty = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}], "usage": {}}
    backend = GroqBackend(credential="dummy-credential", post=FakeGroq([empty]))

    try:
        backend.generate("system text", "user text")
    except RuntimeError as error:
        assert "no answer text" in str(error) and "length" in str(error)
    else:
        raise AssertionError("an empty reply must not become an answer")


def test_groq_waits_as_long_as_a_rate_limit_asks_then_tries_again():
    post, waits = FakeGroq([RateLimited(7.0), GROQ_REPLY]), []
    backend = GroqBackend(credential="dummy-credential", post=post, sleep=waits.append)

    generation = backend.generate("system text", "user text")

    assert waits == [8.0] and len(post.calls) == 2
    assert generation.text == "Hypomagnesemia was reported [1]."


def test_groq_stops_with_a_clear_message_when_the_wait_is_hours():
    """A daily limit answers with a wait of hours: stop, do not sleep."""
    post, waits = FakeGroq([RateLimited(7200.0)]), []
    backend = GroqBackend(credential="dummy-credential", post=post, sleep=waits.append)

    try:
        backend.generate("system text", "user text")
    except RuntimeError as error:
        assert "120 minutes" in str(error) and waits == []
    else:
        raise AssertionError("a wait of hours must stop the run")


def test_groq_without_a_credential_says_where_to_put_it(monkeypatch, tmp_path):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("rag.generate.backends.ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr("rag.generate.backends.read_env_file", dict)

    try:
        GroqBackend()
    except RuntimeError as error:
        assert "GROQ_API_KEY is not set" in str(error)
    else:
        raise AssertionError("a missing credential must stop the backend")


def test_read_env_file_reads_names_and_values_and_skips_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# a comment\nDATA_DIR=D:/capstone/data\nQUOTED='two words'\n\nnot a pair\n", encoding="utf-8")

    assert read_env_file(env) == {"DATA_DIR": "D:/capstone/data", "QUOTED": "two words"}
    assert read_env_file(tmp_path / "missing.env") == {}


def test_every_request_names_its_own_user_agent(monkeypatch):
    """Groq answers Python's default user agent with 403 'error code: 1010'."""
    seen = {}

    def fake_urlopen(request, timeout):
        seen["agent"] = request.get_header("User-agent")
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(backends.urllib.request, "urlopen", fake_urlopen)

    assert backends.post_json("https://example.invalid", {}) == {"ok": True}
    assert seen["agent"] == backends.USER_AGENT


def test_a_lazy_backend_is_built_only_when_an_answer_is_generated(monkeypatch):
    """A question the guardrail refuses must not need a key or a server."""
    built = []

    class Real:
        def generate(self, system, user):
            return backends.Generation("An answer [1].", 0.1, 10, 5, "real")

    monkeypatch.setattr(backends, "make_backend", lambda name: built.append(name) or Real())
    lazy = backends.LazyBackend("groq")

    assert built == []
    assert lazy.generate("system", "user").text == "An answer [1]."
    lazy.generate("system", "user")
    assert built == ["groq"]
