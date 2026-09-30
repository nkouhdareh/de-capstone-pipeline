# ADR-016: No separate vector store; exact search in process

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-09-30 |
| **Deciders** | Nastaran Kouhdareh |

This is ADR-016, not ADR-006. [ADR-015](ADR-015-retrieval-extension-not-built.md) states that
the reserved numbers ADR-006 and ADR-008 "remain unused rather than being reassigned", so that
`technical_requirements.md` §1 stays traceable to the decision that was consciously not taken.

## Context

TR-52 named Postgres with pgvector and an HNSW index; the resumed plan named Qdrant. Both choices
were made before anything was measured. By the end of Phase 4 the retrieval core existed without a
store: 360,916 arctic-embed-s vectors in one numpy file searched exactly, a hand-rolled BM25 index,
and RRF fusion in Python, together beating dense alone on the dev split (recall@5 0.471 to 0.588,
paired +0.118 [+0.029, +0.206]). The query-time drug filter, the main reason to want a store with
filtered HNSW, was measured and not built (its ceiling at recall@5 is +0.044 [-0.015, +0.118]).
Hardware is one CPU laptop with 16 GB, and the consumer is a Streamlit tab for one user at a time.

Measured on dev (`python -m rag.eval.ann_recall`, faiss 1.15.1 HNSW, M 32, efConstruction 200):

| | exact (numpy) | HNSW efSearch 128 | HNSW efSearch 256 |
|---|---|---|---|
| search time, p50 | 18.8 ms | 0.40 ms | 0.64 ms |
| embedding the question | 7.9 ms | 7.9 ms | 7.9 ms |
| recall@20 against exact | 1.000 | 0.939 | 0.973 |
| worst single question | 1.00 | **0.00** | 0.75 |
| build | none | 58 s | 58 s |
| extra on disk and in memory | none | 653 MB index (the vectors are 554 MB) | same |
| hybrid on the gold set, paired | | 1 question better, 0 worse at recall@5 | |

The question HNSW lost entirely is a negative (a drug not in the corpus): with nothing truly close,
the graph walk ends in the wrong neighbourhood. That is the case the refusal guardrail depends on.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A: no store; vectors in a numpy file, exact search, BM25 and RRF in process (chosen)** | Exact by definition, so no recall to monitor; 19 ms search next to seconds of LLM generation; nothing to run, deploy or keep in sync; every step is readable Python, which was a design goal; fits the offline Parquet and DuckDB stack the app already uses | Search time grows linearly with the corpus; the whole matrix sits in RAM (554 MB); no filtering, persistence or concurrency features |
| B: Qdrant in a container | Filterable HNSW, native sparse vectors and server-side fusion, int8 quantisation | Another container for one user; its two strengths, filtered search and fusion, are not needed now; HNSW recall has to be monitored |
| C: Postgres and pgvector (TR-52) | SQL joins to the marts; one familiar database | Postgres full-text ranking is not BM25; slow HNSW builds; a database server for a read-only index |
| D: LanceDB, embedded | No server; Parquet-like files | Adds a store to do what one numpy file does; approximate by default |
| E: DuckDB `vss` and `fts` | Already a dependency; real BM25 in `fts` | HNSW persistence in `vss` is experimental; the hybrid would still be fused in Python |
| F: faiss HNSW in process | 50 times faster search | Measured above: 0.94 recall@20 with a worst case of 0, 653 MB more memory, a minute's build, for a saving users cannot see |

## Decision

We chose **A**. At 360,916 vectors exact search takes 19 ms and is always right, so an approximate
index would trade a guaranteed answer for a saving of about 18 ms, invisible next to answer
generation. A store would add a service whose main features, filtered and fused search, this
system either does not need or already does in a few lines.

## Consequences

**Positive:** no service to run; the published recall numbers are exactly what users get; the
index is two versioned folders with manifests (`arctic-s-fp32`, `bm25-v1`), rebuilt by one command
each.

The pipeline that runs on this decision (dense and BM25 fused by RRF, near-copies collapsed) was
scored once on the held-out test split on 2026-09-30, 46 answerable questions: recall@5 0.609
against 0.500 for dense alone (paired +0.109 [-0.022, +0.239], not clear of zero), recall@1 0.435
against 0.283 (paired +0.152 [+0.043, +0.261], clear), at 60 ms a question.

**Negative / accepted trade-offs:** latency grows with the corpus, about 5 ms per 100,000 chunks;
about 850 MB of RAM for dense search and 210 MB for BM25; no incremental updates, since a new
label means rewriting the vector file (the dense build is a 10.8-hour job on this laptop, whatever
the store).

**Revisit if:** the corpus passes roughly 2 to 3 million chunks (exact search then nears 150 ms);
several users query at once; a working metadata filter is needed after all; or labels must be added
without a rebuild. First candidate then: Qdrant for filtered HNSW, efSearch at least 256, with ANN
recall measured by `rag/eval/ann_recall.py` against this exact baseline.
