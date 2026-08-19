# ADR-009: Hybrid deployment — Bronze and Silver compute stay on local disk

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-03 |
| **Deciders** | Nastaran Kouhdareh |

## Context

The capstone guide states plainly that a project may be implemented fully on the cloud,
fully locally, or as a hybrid — and that **the decision should be documented in an ADR**.

The technical requirements as originally written (TR-05/06/07) put Bronze in S3 as
gzipped NDJSON with per-file manifests. Once the data was actually downloaded, the shape
of the problem changed: **Bronze is 64 GB** for 24 months (drug_event 56 GB, drug_label
8 GB, drug_ndc 168 MB). The Silver output derived from it is **3.9 GB** — roughly one
sixtieth of the size.

Available budget was ~$182 of AWS credits and a $400 Snowflake trial. The laptop was
already paid for.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Hybrid: Bronze and Spark local, Silver + warehouse in the cloud (chosen)** | Uploads only the ~8 GB the warehouse actually needs; ~$0.20/month of S3; no egress; the expensive resource is used only where it is genuinely faster | Not production-shaped; the pipeline cannot be run by someone who clones the repo without also downloading 64 GB |
| B — Fully cloud: Bronze in S3, Spark on Glue/EMR | Production-shaped; a reviewer can run it; horizontal scale would cut the 4-hour Silver build to ~20 minutes | 64 GB in S3 ≈ $1.60/month, plus the upload; Glue/EMR bills $0.50–2 per cluster-hour and would have consumed a meaningful share of the credits during development, when the job was re-run many times. Also a significant rebuild in a three-week window |
| C — Fully local: DuckDB or Postgres instead of Snowflake | Free forever; runnable indefinitely by anyone | No cloud-warehouse skill demonstrated, which is an explicit portfolio goal ([ADR-002](ADR-002-warehouse-snowflake.md)); no external-stage or IAM story |
| D — Bronze in S3, Spark still local | Satisfies TR-06 literally | Pays to store 64 GB that only the local Spark job ever reads, then downloads it again to process it. Cost with no benefit |

## Decision

We chose **A**. The governing observation is that **Bronze has exactly one consumer** —
the local Spark job — and that consumer is on the same machine as the data. Putting 64 GB
into object storage so a process running two inches away can read it back adds upload
time, storage cost and egress risk in exchange for nothing.

Silver is different: it has a *remote* consumer (Snowflake), it is small enough to move,
and turning it into an S3 object gives it properties an internal stage cannot offer
([ADR-011](ADR-011-s3-external-stages.md)). So the boundary between local and cloud was
drawn exactly where the data crosses machines.

The hybrid split is, incidentally, the cheapest possible arrangement: the expensive
resource (cloud compute) is used for the two minutes it is genuinely faster at, and the
free resource (hardware already owned) absorbs the four hours.

## Consequences

**Positive:** **Money actually paid: about $0.25**, plus $42 of a $400 Snowflake trial —
against a target of under $10 of real spend. Only ~8 GB is in the cloud. The orchestration
layer that normally dominates a data-platform bill costs nothing, because Airflow, Spark
and dbt all run on hardware already owned; managed Airflow alone would start around
$350/month. At ten times the data, S3 would still cost under $1/month.

**Negative / accepted trade-offs:**

- **TR-05, TR-06 and TR-07 are not met.** Bronze is uncompressed NDJSON on local disk
  with no manifests. The gzip and manifest gaps are genuine and are not defended by this
  ADR — they were simply never built.
- **TR-63 (cold start in one command) becomes unachievable.** A reviewer cannot clone and
  run without a 30–60 minute download and ~70 GB free.
- The real ceiling moves from money to **laptop disk and Spark runtime**: 64 GB and
  ~4 hours for 24 months; ten years would be ~320 GB and roughly twenty hours.

**Revisit if:** the history extends beyond about five years, or the pipeline needs to run
somewhere other than this machine. The honest next step is to move the Silver step to
managed Spark — AWS Glue or EMR — which trades hours of waiting for a few dollars per run.
The strongest alternative is more radical: **delete Spark entirely and flatten the JSON in
Snowflake**, which reads nested JSON natively and would likely turn four hours into
minutes, at the cost of removing the one idiomatic Spark job the project was partly built
to demonstrate.
