# ADR-017: A hosted model answers by default; a local model stays behind the same interface

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-09-30 |
| **Deciders** | Nastaran Kouhdareh |

This is ADR-017, not ADR-008. [ADR-015](ADR-015-retrieval-extension-not-built.md) keeps the
reserved numbers ADR-006 and ADR-008 unused.

## Context

Retrieval returns five chunks behind a refusal guardrail. Something has to turn them into an
answer a person reads, with citations, in a dashboard tab. The original design (the reserved
ADR-008) named local Ollama. Constraints: a CPU-only laptop (i5-1334U, 16 GB); free;
no Chinese-published models; medical text, so a wrong or unsourced answer is not a neutral bug.

Both candidates sit behind one interface (`rag/generate/backends.py`) and were measured on the same
questions with the same retrieval, prompt and citation check (`rag/eval/answer_eval.py`). The
decision was taken on the 83 dev questions:

| dev, 83 questions | local: Ollama `llama3.2:3b` (Meta) | hosted: Groq `openai/gpt-oss-120b` (OpenAI open weights) |
|---|---|---|
| seconds per answer | **62** (p95 84) | **about 1**; 16 in a batch, waiting on the free plan's per-minute limit |
| answers passing the citation check | 39 of 64 (61%) | **58 of 61 (95%)** |
| sentences with no citation | 14 of 157 | 0 of 70 |
| sentences not supported by what they cite | 19 of 157 | 3 of 70 |
| refused although the answer was in its top 5 | 1 | 0 |
| answers citing a gold chunk | 30 of 63 | 40 of 60 |
| answers stating the gold answer's words | 51 of 63 | 51 of 60 |
| negatives refused | 14 of 15, all by the guardrail | 14 of 15, all by the guardrail |
| needs | nothing: no key, no network | a free account, a key in `.env`, a network |
| the question leaves the laptop | no | yes |

It was then checked once on the 56 held-out test questions, with nothing tuned afterwards:

| test, 56 questions | local | hosted |
|---|---|---|
| answers passing the citation check | 30 of 45 (67%) | **36 of 39 (92%)** |
| sentences with no citation | 5 of 139 | 1 of 50 |
| sentences citing a source that does not exist | 0 of 139 | 0 of 50 |
| sentences not supported by what they cite | 19 of 139 | 2 of 50 |
| refused although the answer was in its top 5 | 0 | 0 |
| answers citing a gold chunk | 24 of 44 | 25 of 39 |
| answers stating the gold answer's words | 37 of 44 | 35 of 39 |
| negatives refused by the guardrail | 9 of 10 | 9 of 10 |
| the negative that passed the guardrail | answered | **refused by the model** |
| seconds per answer | 61 (p95 79) | about 1 when not waiting on the free plan's limit |

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A: hosted by default, local behind the same interface (chosen)** | A second per answer makes the tab usable; the hosted model follows the citation and refusal rules (95% against 61% on dev, 92% against 67% on test); the local path keeps the project reproducible with no key and no network; swapping is one argument | Two code paths to keep working; the demo depends on a free plan whose terms and model list can change, which already happened once here |
| B: local only (the original design) | Fully reproducible and private; nothing to sign up for | A minute per answer on this CPU; 3 to 4 answers in 10 break the citation rule |
| C: hosted only | Least code | Anyone cloning the repo needs an account; one provider change breaks the tab |
| D: a larger local model (`gemma3:4b`, `mistral:7b`) | Might follow the rules better, still private | Slower still than the 3B model on the same CPU; not measured, so not claimed |
| E: Gemini Flash free tier | Fast, capable | Its free tier's pricing page states content is used to improve Google's products |

## Decision

We chose **A**. The measurement decides it on two counts: a minute against a second, and 61%
against 95% of answers passing the citation check. The test split confirmed both (61 s against
about 1 s; 67% against 92%). The local model stays because a portfolio project that cannot run
without someone else's account is not reproducible, and because the interface makes keeping it
cost almost nothing.

Two things hold for either backend, and matter more than the choice between them:

- **The guardrail, not the model, does the refusing.** On dev neither model refused a single
  negative on its own, and both answered the one that slipped past the guardrail. On test the
  hosted model did refuse the one that slipped past; the local model answered it. One case each
  way is not something to rely on, so refusal stays in retrieval.
- **Citations are checked by code, not trusted.** The check also had to be fixed twice (rarity
  weighting; gpt-oss's own citation style), and `--recheck` re-scores saved answers when it changes.

## Consequences

**Positive:** the tab answers in about a second with every sentence cited; `--backend ollama`
reproduces the whole pipeline offline; a third backend is one small class.

**Negative / accepted trade-offs:**

- The hosted path sends the user's question and five label chunks to Groq (public label text, but
  a third party).
- The free plan's limits cap batch evaluation. The 83 dev questions took about 20 minutes. The
  test run fell on the same day as the dev runs, met the daily limit, and needed about three hours
  of automatic retries to finish 56 questions. A single question in the tab does not wait.
- The first-choice model, `llama-3.3-70b-versatile`, was in Groq's documentation and not available
  to a free account, so the comparison is a small local model against a large hosted one from a
  different family, not one family at two sizes.
- The local model can fail in ways the hosted one did not. On one test question it repeated a
  correct sentence without stopping; the backend had no limit on answer length and the request
  ran into its 10-minute timeout. Both backends now share one cap (1,500 tokens). The test split
  found this; dev did not.
- The local model's flagged sentences are shown to the user as flagged, not hidden.

**Revisit if:** Groq's free plan or its model list changes; a GPU or a faster CPU makes a 7B to 12B
local model answer in a few seconds; or the tool is used with anything other than public text, where
the hosted path would have to go.
