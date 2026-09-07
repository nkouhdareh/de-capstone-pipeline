# Retrieval extension (RAG) over openFDA drug labels

Answers natural-language questions about drug-label content and cites the source
label section, or states that the question falls outside indexed scope.

Closes **BR-16**, **BR-17** and **TR-50 ... TR-57**, recorded as deliberately not
built in [ADR-015](../docs/adr/ADR-015-retrieval-extension-not-built.md).

## Status

| Phase | State |
|---|---|
| Scaffold | done |
| 0 Explore the label corpus | in progress |
| 1 Corpus scoping and chunking | not started |
| 2 Gold set and evaluation harness | not started |
| 3 Dense retrieval baseline | not started |
| 4 Hybrid retrieval, vector store decision (ADR-006) | not started |
| 5 Reranking, diversity, guardrail | not started |
| 6 Generation and Streamlit tab (ADR-008) | not started |

Nothing here is wired into the dashboard yet.

## Design decisions fixed up front

**Chunks are never keyed on `drug_key`.** [ADR-005](../docs/adr/ADR-005-drug-name-resolution-tiers.md)
records that `normalize_drug_name` strips mineral salts, collapsing `sodium chloride`
and `calcium chloride` to `CHLORIDE`. Fixing it regenerates every `drug_key` and needs a
live warehouse. Chunks are keyed on `set_id` and `product_ndc`, and drug identity is
resolved at query time, so a later regeneration invalidates a join rather than the
embeddings or the evaluation set.

**`set_id`, not `id`.** openFDA `id` is version-specific; `set_id` is stable across label
revisions. The current snapshot holds one version per label, so they are 1:1 today and
the difference would stay hidden until the corpus is refreshed.

**Evaluation before optimisation.** The gold set and a harness that runs in under a
minute come before any retrieval tuning. An unmeasured retrieval layer is worth less
than none, which is the argument ADR-015 used to decline building this under deadline.

**No orchestration dependency.** `rag/` reads Bronze JSONL and the offline Parquet marts
directly. It needs no Snowflake, no Airflow and no Spark.

## Layout

| Path | Contents |
|---|---|
| `notebooks/` | Corpus exploration |
| `corpus/` | Scope filter, SPL parsing, chunker |
| `index/` | Embedding models and vector store clients |
| `retrieve/` | Dense, BM25, fusion, reranking |
| `generate/` | LLM backends behind one interface |
| `eval/` | Gold set and the evaluation harness |
| `tests/` | Unit tests |

## Setup

A separate environment from `.venv`, `.venv-app` and `.venv-dbt` on purpose: the
embedding stack added in Phase 3 conflicts with Airflow's pinned dependencies, the
same collision that put dbt in its own container.

    py -3.11 -m venv .venv-rag
    source .venv-rag/Scripts/activate        # Git Bash on Windows
    python -m pip install -r rag/requirements.txt

## Data

| Source | Role |
|---|---|
| `data/bronze/drug_label/` (8.55 GB, 261,258 records) | The corpus. The only source embedded. |
| `data/offline/int_drug_resolution.parquet` | Query-time drug name resolution |
| `data/offline/dim_drug.parquet` | Drug identity for filtering |

`data/bronze/drug_event/` is not used here. It is structured report counts and is
already represented in the marts.
