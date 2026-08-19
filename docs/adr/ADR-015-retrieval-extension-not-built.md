# ADR-015: The retrieval (RAG) extension was not built

| | |
|---|---|
| **Status** | Accepted — supersedes the reserved ADR-006 and ADR-008 |
| **Date** | 2026-08-18 |
| **Deciders** | Nastaran Kouhdareh |

## Context

The business requirements included a retrieval capability over drug-label text (BR-16,
BR-17): chunk the label sections, embed them, and let an analyst ask *"is this reaction
already listed on the product's label?"* with a cited source. The technical requirements
specified it in detail as TR-50 … TR-57 — SPL-section chunking, `all-MiniLM-L6-v2`
embeddings, Postgres with `pgvector` and an HNSW index, metadata pre-filtering, a
similarity guardrail, and a gold evaluation set of at least 30 question/chunk pairs with
recall@5 measured and published.

Two ADR numbers were reserved for its component choices — **ADR-006** (pgvector rather
than Elasticsearch or Qdrant) and **ADR-008** (local Ollama rather than a hosted API).
Neither was ever written, because neither decision was ever reached.

Crucially, this was **planned from the start as a droppable extension**.
`business_requirements.md` §8 states it plainly:

> The retrieval capability (BR-16, BR-17) is an **extension**, not a core deliverable. It
> will be built only after all Must requirements in §5.1–5.3 are satisfied, and work on it
> stops on **18 August** regardless of state. If it is not delivered, that will be
> recorded as a deliberate scope decision.

This ADR is that record.

## What happened instead

By the 18 August hard stop, the time the extension was reserved for had been spent on work
that was not in the original plan and turned out to matter more:

| Instead of the extension | Delivered |
|---|---|
| — | Airflow orchestration proven at full scale — 8 tasks, 3 h 57 m 23 s, in dependency order |
| — | The S3 external-stage cutover ([ADR-011](ADR-011-s3-external-stages.md)) |
| — | Snowflake key-pair migration ahead of the 18 August deprecation ([ADR-012](ADR-012-snowflake-key-pair-service-identity.md)) |
| — | A third dashboard, hosted inside Snowflake, so the demo is a URL |
| — | Four CI/CD workflows and eight checks, each gate proven by making it fail |
| — | Terraform managing the CI IAM role ([ADR-014](ADR-014-terraform-ci-role-only.md)) |
| — | 21 pytest unit tests for TR-37 and TR-38 |

Two of those were not optional. The Snowflake password deprecation on 18 August would have
broken four of the eight DAG tasks; migrating was survival, not scope creep.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Do not build it; record the decision (chosen)** | Honours the pre-agreed hard stop; the time went into orchestration, security and CI, which are graded criteria and which the extension is not; the core pipeline stays verified and frozen | Loses the RAG story, which is currently fashionable and would have been a visible differentiator |
| B — Build a minimal version in the remaining days | Something to demo; the embeddings and pgvector work is not large | Three new-to-me technologies (pgvector, sentence-transformers, Ollama) at ~1.25 days of learning cost, landing during the number freeze. TR-56 requires a **measured** recall@5 over a 30-question gold set — without that it is a demo, not engineering, and an unmeasured retrieval layer is worth less than none |
| C — Build it and drop something else | Keeps the feature | The only things large enough to trade were CI/CD or the orchestration proof. Both are explicitly graded; the extension is not |
| D — Leave it silently unbuilt | No work at all | Breaks a commitment made in writing at the Gate-1 review, and leaves TR-50…57 and BR-16/17 looking simply unaddressed rather than decided |

## Decision

We chose **A**. The extension was scoped as droppable precisely so that this decision
could be taken without damaging the core, and the hard stop existed so it would be taken
on time rather than late.

**ADR-006 and ADR-008 are hereby superseded by this record.** Their numbers remain unused
rather than being reassigned, so that existing references to them in
`technical_requirements.md` §1 remain traceable to a decision that was consciously not
taken.

## Consequences

**Positive:** The core pipeline was never destabilised in its final week. Every figure
documented on 13 August still held on 19 August. The three days went into work that is
directly named in the evaluation criteria — orchestration, testing, security and CI/CD —
rather than into a fourth data domain. The drug-label data (261,258 records) is already
ingested and sitting in Bronze, so the extension remains genuinely startable rather than
hypothetical.

**Negative / accepted trade-offs:** No demonstrated experience with vector search,
embeddings or LLM integration, which is a real gap against current job descriptions and
should be expected as a question. The honest answer is this ADR: it was scoped as
droppable, it hit its pre-agreed stop date, and the alternative was an unmeasured demo
built during a change freeze.

Two requirement sets are therefore unmet and are recorded as such: **BR-16, BR-17** and
**TR-50 … TR-57**.

**Revisit if:** the project is picked up after submission. The natural first step is
unchanged from the original design — chunk by SPL section (a label section *is* the
natural retrieval unit, so no chunk-size tuning is needed), pre-filter on `drug_key` and
section type in SQL, then rank by similarity within that candidate set. The evaluation set
is the part to build first, not last.
