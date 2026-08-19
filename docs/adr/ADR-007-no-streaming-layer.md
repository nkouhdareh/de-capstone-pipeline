# ADR-007: No streaming layer — batch ELT only

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-02 |
| **Deciders** | Nastaran Kouhdareh |

## Context

Streaming appears in most data-engineering job descriptions, and a Kafka or Kinesis
component is a visible skill signal in a portfolio project. The capstone guide explicitly
asks for a pipeline architecture pattern to be selected — Lambda, Kappa, or a suitable
variation.

But the data does not stream. FAERS is a **spontaneous reporting system**: a clinician or
patient files a report, the FDA processes it, and openFDA publishes it in periodic
batches. There is no event feed, no webhook, no change-data-capture endpoint. The
project's working window is a fixed historical snapshot — 2023-01-01 to 2024-12-31 —
which by definition cannot arrive in real time.

The analytical question also has no latency requirement. Disproportionality statistics
need *accumulated* counts; a signal is only meaningful once enough cases exist to clear a
minimum of three, and the headline finding rests on 5,571 cases gathered over 24 months.
Nobody makes a drug-safety decision on a report that arrived ninety seconds ago.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Batch ELT, medallion layering (chosen)** | Matches how the source actually publishes; idempotent and backfillable by construction; the entire three-week budget goes into data quality, orchestration and testing rather than into infrastructure | No streaming skill demonstrated — a gap interviewers probe |
| B — Synthetic stream: replay historical reports through Kafka/Redpanda at an artificial rate | Produces a streaming component to point at; Kappa architecture becomes describable | The stream carries no information the batch does not. It adds a broker, a consumer, delivery semantics and a failure surface to *re-deliver data already on disk*. It would also be visibly contrived to anyone who knows the source, which is worse than not having it |
| C — Lambda: batch path plus a "speed layer" over the most recent days | Textbook pattern; genuinely useful when a source is continuous | The speed layer would serve statistics computed on too few cases to mean anything. It answers a question no user asks |
| D — Poll the API frequently and call it micro-batch | Cheap to implement | The source updates in batches regardless of poll frequency; it is batch with a shorter interval and a misleading label |

## Decision

We chose **A**, and state the reasoning rather than hiding the gap:

> A synthetic stream would add risk and moving parts without adding information. An
> honest batch pipeline with a documented justification is a better engineering answer
> than a contrived streaming layer.

This was raised explicitly at the business-requirements gate — *"My data is inherently
batch. Is a contrived streaming layer preferable to an honest batch pipeline with a
documented justification?"* — and batch was carried forward.

The batch choice is not a limitation dressed as a decision. Date-partitioned extraction
is what makes ingestion **idempotent** (re-running a day yields the same rows),
**resumable** (delete the last partial day, restart from it) and **backfillable** (the
same code with different dates). A streaming design would have had to rebuild each of
those properties.

## Consequences

**Positive:** The whole effort went into the parts that carry the grade and the value —
deduplication at a declared grain, drug identity resolution, quarantine with reasons,
eight-task orchestration, 42 data tests, and CI gates proven by making them fail. The
pipeline can reprocess two years of history from an immutable Bronze layer without
touching the API.

**Negative / accepted trade-offs:** No hands-on evidence of Kafka, Flink or Spark
Structured Streaming, which is a real gap against job descriptions and will be asked
about. The answer given is this ADR: the tool was rejected because the source does not
justify it, not because it was unfamiliar.

**Revisit if:** a genuinely continuous source is added — an internal pharmacovigilance
inbox, an EudraVigilance feed, or a hospital reporting system. At that point a Kappa
design over the new source, joined to the batch marts, would be doing real work rather
than performing.
