# Retrieval extension (RAG) over openFDA drug labels

Answers natural-language questions about drug-label content and cites the source
label section, or states that the question falls outside indexed scope.

Closes **BR-16**, **BR-17** and **TR-50 ... TR-57**, recorded as deliberately not
built in [ADR-015](../docs/adr/ADR-015-retrieval-extension-not-built.md).

## Status

| Phase | State |
|---|---|
| Scaffold | done |
| 0 Explore the label corpus | **done** |
| 1 Corpus scoping and chunking | **done** |
| 2 Gold set and evaluation harness | **done** |
| 3 Dense retrieval baseline | **done** |
| 4 Hybrid retrieval, vector store decision (ADR-016) | **done** |
| 5 Reranking, diversity, guardrail | not started |
| 6 Generation and Streamlit tab (ADR-017) | not started |

Nothing here is wired into the dashboard yet.

## What Phase 0 measured

A full pass over all 261,258 Bronze label records (61 s), flattened to two narrow Parquet
files so every question is a SQL query rather than a re-read of 8.5 GB. See
`notebooks/01_explore_drug_label.ipynb`; its outputs are committed.

| Measurement | Result |
|---|---|
| Schema | 183 field paths, 2 levels deep. Every field `array<string>` except `openfda.is_original_packager` |
| Attributable records | 86,367 of 261,258 (**33.1%**) carry `openfda` metadata |
| Exact-duplicate section text | **59.4%** (4,442,377 texts, 1,803,438 distinct) |
| Label types | 37,018 prescription, 49,328 OTC, 21 cellular therapy |
| Identity | `set_id`, `id` and record count all exactly 261,258 |

Three of these overturned assumptions taken from single-file samples, and two are worth
stating because they change the code:

**`openfda` is present on 100% of records but its subfields on only 33.1%.** The block
exists as an empty object two thirds of the time, so `"openfda" in record` is true for every
record and is the wrong test. Testing the value admits 86,367 records; testing the key would
have admitted ~175,000 unattributable ones.

**TR-50 fails per section, not outright.** `use_in_specific_populations` overflows a
512-token window 94.6% of the time and `warnings_and_cautions` 83.5%, but `contraindications`
only 3.2%. The chunker needs a keep-whole path and a split path rather than one rule.

**Scoping to prescription-only was tested and rejected.** OTC labels outnumber prescription
ones (49,328 vs 35,877) but carry 21 times less text, so including them costs 4.8% more
chunks. Excluding them would have removed the drugs the highest-value FAERS questions are
about: acetaminophen, ibuprofen, aspirin, naproxen, diphenhydramine.

That test also exposed a second error. The original 10-section allowlist was
prescription-shaped. OTC labels put safety content in different fields, all short: `stop_use`
(29,507 labels, 172 chars average), `when_using` (23,173), `do_not_use` (22,453),
`ask_doctor` (17,155). Those are now included.

**The corpus therefore has two opposite chunking problems.** Prescription sections are few
and enormous and must be split; OTC sections are six per label and roughly 40 tokens each and
must be merged. One rule solves both: target 350 to 450 tokens, split what is over, merge what
is under.

The v1 corpus is therefore **86,367 labels across a 16-section allowlist, roughly 692,000
chunks before deduplication and about 285,000 after.**

### Phase 1 result

86,367 labels chunked in 37 minutes into **360,916 chunks**, from 851,377 before
deduplication removed 57.6%. No chunk exceeds 512 tokens. Phase 0's projections held:
it predicted 86,367 labels (exact), a ~59.4% duplicate rate (57.6% actual) and about
340,000 chunks (360,916 actual).

Both chunking paths are exercised, which is why the two-path design exists: 26% of
prescription sections were small enough to keep whole, while 70% needed splitting.

### Phase 2 result

**139 questions, every one checked by hand**, in `eval/gold/gold.jsonl`: 42 direct
lookups, 33 yes/no verifications, 24 paraphrases, 15 exact identifiers, and 25 hard
negatives whose answer is deliberately not in the corpus. Split 60/40 into dev and test,
stratified by question type, so nothing is tuned and reported on the same questions.

Candidates were sampled deterministically, 12 per section, and the verification questions
come from this project's own FAERS signals, so retrieval is tested against the
drug-reaction pairs the pipeline already found. An LLM drafted the questions and all 140
were then reviewed by hand: 134 kept as drafted, 5 corrected, 1 dropped.

A gold question stores `(set_id, section, answer_span)` and never a chunk id, because
every chunk id changes when the chunker changes. `eval/gold.py` maps an anchor onto the
chunk ids of the current index in one second, and all 114 answerable questions resolve.

`python -m rag.eval.run_eval` takes **1.2 seconds** against a 60 second budget, and proves
itself on two baselines: a retriever that cannot be wrong scores 1.000 on every metric,
and one that cannot be right scores 0.000. Metrics are recall@1/5/10/20, MRR@10 and
nDCG@10, each with a 95% bootstrap interval, because at n=56 on the test split a 3 point
difference is noise.

### Phase 3 result

Every chunk is embedded with `snowflake-arctic-embed-s` (Snowflake, US, Apache 2.0). It
replaced the first pick, `BAAI/bge-small-en-v1.5`, for provenance: the same size, the same
512-token window and the same tokenizer vocabulary, so the Phase 1 chunks stayed valid.
**360,916 vectors in 10.8 hours** on a laptop CPU, at 9.3 chunks per second in full
precision. The builder saves every 10,000 chunks and resumes after an interruption, writes a
manifest per index, and refuses to mix two different builds.

On the 68 answerable dev questions, with exact search at 26 ms per question:

| | recall@1 | recall@5 | recall@10 | recall@20 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|---|
| dense, arctic-embed-s | 0.235 | **0.471** | 0.662 | **0.750** | 0.351 | 0.421 |
| the same, without the query prefix | 0.191 | 0.382 | 0.485 | 0.618 | 0.286 | 0.331 |

Four findings came from measuring rather than assuming:

- **The first ruler was wrong.** The first run scored 0.294. A third of its misses were
  correct answers from another manufacturer's label of the same drug, so a question now counts
  any chunk holding its exact answer text, in the same section, for the same drug. The strict
  score, the question's own label only, is still printed beside it.
- **fastembed does not add arctic's query prefix.** That was read from its source, then added
  in code and pinned by a test. Without it, recall@5 falls from 0.471 to 0.382.
- **2,732 chunks (0.76%) would have been silently cut** once their header was added, because
  some drug names run to 237 tokens. The model now reads a compact header, trimmed until every
  chunk fits.
- **recall@20 is 0.28 above recall@5.** The answer is often retrieved but ranked too low,
  which is what a reranker fixes, so Phase 5 is justified by measurement.

### Phase 4 result

Keyword search (BM25) now runs beside dense search, and the two ranked lists are fused
with Reciprocal Rank Fusion (RRF). BM25 is hand-rolled on numpy: Snowball stemming,
Lucene's 33 stopwords, and raw counts stored term by term, so its two settings can change
without a rebuild. Its index builds in **30 seconds**; the dense one took 10.8 hours.

Every claim is now a **paired comparison**: for each question, B's score minus A's, with a
bootstrap interval of those differences. On the 68 answerable dev questions:

| | recall@1 | recall@5 | recall@10 | recall@20 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|---|
| dense | 0.235 | 0.471 | 0.662 | 0.750 | 0.351 | 0.421 |
| BM25 | 0.324 | 0.485 | 0.574 | 0.721 | 0.390 | 0.433 |
| **hybrid, RRF k = 60** | **0.353** | **0.588** | **0.691** | **0.824** | **0.446** | **0.504** |

Hybrid against dense, paired: recall@5 **+0.118 [+0.029, +0.206]**, better on 9 questions
and worse on 1; nDCG@10 +0.083 [+0.017, +0.150].

- **BM25 and dense tie, but fail on different questions**, 11 wins to 10 at recall@5,
  which is the condition for fusion to help. Fused, paraphrase questions rise from 0.214 to
  0.357 and lookups from 0.440 to 0.600, above either retriever alone.
- **k stays at the textbook 60.** Of 18 settings swept on dev, k = 20 came first, but it
  differs from k = 60 on 3 questions of 68. Normalised weighted sums lost to RRF at every
  weight tried.
- **The drug-name filter (TR-53) was measured, not built.** Even a perfect detector, the
  gold set's own drug names, adds recall@5 +0.044 [-0.015, +0.118]: hybrid's top 5 is
  already the right drug 83.5% of the time. Detecting drugs from question text is unreliable
  (brands named "The", "Pain", "Water"), and a wrong detection hides the right answer.
- **No separate vector store** (ADR-016, written up in Phase 7). Exact search takes 19 ms and is
  always right. faiss HNSW takes 0.4 ms but finds 0.939 of the exact top 20, and none of it
  for one question, for a saving nobody sees next to an LLM answer.

### Known limitation

The remaining **174,891 labels (66.9%) are out of scope**, because openFDA could not
harmonise them to the NDC directory and they carry no brand name, generic name or NDC. They
are not unidentifiable, only unharmonised: 99.8% carry a product name in
`spl_product_data_elements` and 63.6% carry an `active_ingredient` field. Between them they
hold roughly 190 million characters of `warnings` text.

They are excluded on **attribution**, not cost. A chunk that cannot be attached to a drug name
cannot be filtered to or cited, and if it surfaces anyway it looks like an answer while being
unusable. Recovering them means resolving free-text ingredient names, which is the
[ADR-005](../docs/adr/ADR-005-drug-name-resolution-tiers.md) problem on a cleaner input.
Deferred and sized, not dismissed.

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

**Deduplication is mandatory, not an optimisation.** At a 59.4% exact-duplicate rate, one
`warnings` text appears on 6,390 labels. Without dedup a matching query returns the same
paragraph as all five top results. It is also what brings the chunk count comfortably inside
the target range.

**Drug identity was planned to resolve at query time through a tiered ladder**, `rxcui`
then brand name then canonical name (measured hit rates 53.5%, 63.8% and 41.4%). Phase 4
measured what a query-time drug filter could add at best and did not build it; see the
Phase 4 result.

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
| `data/offline/int_drug_resolution.parquet` | Not used: the query-time drug filter was measured and not built (Phase 4) |
| `data/offline/dim_drug.parquet` | Drug identity for filtering |

`data/bronze/drug_event/` is not used here. It is structured report counts and is
already represented in the marts.
