# Silver layer — design rationale & defense notes

*Why the Silver layer is built the way it is, and how to defend the choices in review.
Operational run steps live in `runbook.md` §2 — this file is the **why**.*

---

## Medallion pattern

**bronze (raw) → silver (cleaned, typed, deduplicated, still granular) → gold (business marts).**

The Silver step here: flatten the nested reports to an atomic grain, cast/decode the all-string
fields, dedup, normalise drug names, validate/quarantine — then write columnar Parquet. The general
shape is standard data-engineering practice; the *specific* choices trace to our own artifacts and
openFDA's specs, not guesswork.

## Where each decision came from

| Decision | Where it came from |
|---|---|
| **Grain = (case, drug, reaction)** | You wrote it — `technical_requirements.md` §5.1 declares `fct_report_drug_reaction` at exactly this grain; your `01_explore` notebook calls exploding to (report, drug, reaction) "the core Silver step". |
| **Cast everything from string** | Your exploration finding: "every field is string" + `docs/Metadata/drug_event_schema.md`. |
| **Decode 1→SUSPECT, etc.** | `docs/Metadata/field_dictionary.md` — machine-generated from openFDA's own `fields.yaml` specs. |
| **#4 dedup / #5 normalise / #6 quarantine** | Your 5-dimension DQ findings + `business_requirements.md` (BR-05/06/07) + `technical_requirements.md` (TR-13…19). |
| **Age banded, not exact** | You wrote it — `technical_requirements.md` §9. |
| **Skew handling** | Your exploration found the max 4,113-drug report. |

> **If asked "how do you know this is the right way?"** — there's no single right way. It's a
> conventional, defensible silver design, and every non-obvious choice traces to openFDA's field
> specs, the exploration results, or a requirement already written down. One nuance worth knowing:
> `technical_requirements.md` §4.1 puts dedup/normalise in dbt's `int_` (intermediate) layer — we do
> it in PySpark Silver now for the "clean data" milestone. The logic is engine-independent (ADR-004),
> so dbt can re-express or consume it later. Being able to say *why it's in this layer* is a strength,
> not a gap.

---

## Why PySpark? Why not pandas? What to say if asked

You already answered this in your own **ADR-004** — and the honest answer there is the strong one.
Don't let anyone push you into pretending this is a big-data necessity. The script:

> "At 2.69M nested reports exploding to tens of millions of rows, pandas loads everything into RAM at
> once and would OOM on a 16 GB laptop — it's all-in-memory or nothing. Spark streams it in
> partitions and spills to disk, so it scales past memory. **But honestly, at this volume DuckDB or
> Polars would also do it.** I chose Spark deliberately to demonstrate a skill that was in ~50% of my
> target job ads, and I documented that trade-off in ADR-004 rather than dressing it up as a big-data
> requirement. The flattening logic is engine-independent, so if I dropped Spark I'd do the same
> transform in dbt/DuckDB."

That move — "I know a simpler tool would suffice, here's why I chose this anyway, and I wrote it
down" — is what makes reviewers trust you. It beats claiming you *needed* Spark.

### The alternatives, honestly

| Tool | Could it do this? | Trade-off |
|---|---|---|
| **pandas** | Only on a *sample* | Single-core, all-in-memory → OOM on the full nested explode. Great for a quick look. |
| **Polars** | Yes | Fast, out-of-core streaming. Fewer "Spark" signals for employers. |
| **DuckDB** | Yes, comfortably | Embedded OLAP SQL, out-of-core, reads JSON/Parquet, `UNNEST` for the arrays. ADR-004 names it as the simpler option. |
| **dbt + Snowflake SQL** | Yes — your *actual* production path | TR §4.1 does exactly this in `int_` models (`FLATTEN`). Spark here is the "extra" skill demo alongside it. |

### PySpark's real limitations (say these if asked "what did it cost you?")

- JVM startup + overhead → **slower than pandas on small data**; the win only appears at scale.
- Here it's **single-node** — parallel across CPU cores, not a real cluster of nodes. Same idea, smaller.
- On Windows it needs **Docker** to avoid `winutils` friction (ADR-004).
- More operational weight than "just run a Python script".

---

*See also: `docs/adr/ADR-004-dbt-and-spark-transformation.md` (the tooling decision),
`runbook.md` §2 "Why Spark, not pandas" (the exploration-time version).*
