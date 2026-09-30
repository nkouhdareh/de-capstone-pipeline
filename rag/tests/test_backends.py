"""Unit tests for the generator interface. A fake HTTP call stands in for
Ollama, so these need no server: CI runs them."""
from rag.generate.backends import OllamaBackend


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
