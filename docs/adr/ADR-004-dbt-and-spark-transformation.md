# ADR-004: dbt for modelling, plus PySpark for semi-structured flattening

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-02 |
| **Deciders** | Nastaran Kouhdareh |

## Context
FAERS records are deeply nested JSON (one report → many drugs, many reactions) that
must be flattened to an atomic grain, then modelled into a star schema with a
PRR/ROR semantic layer. The modelling work is overwhelmingly SQL-shaped. Separately,
PySpark is the highest-demand processing tool in my job-ad sample (50%) and I want
hands-on evidence of it. The working data is a sliced subset of the 20M reports —
comfortably single-node.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — dbt for modelling + PySpark for bronze→silver flattening (chosen)** | SQL work stays in dbt (tests, lineage, docs); Spark gets one idiomatic job (`explode` nested arrays); demonstrates a 50%-demand skill; clean split of roles | Adds a tool and ~1 day; not required by the volume |
| B — dbt / DuckDB only (engineering-optimal) | Simplest, fastest, sufficient at this volume | No Spark evidence — a gap interviewers probe |
| C — Spark for everything | Single processing engine | Poor fit for SQL modelling; loses dbt tooling; heavier |

## Decision
We chose **A**. dbt remains the transformation engine for all SQL modelling; PySpark
is introduced in **week 2**, scoped to the one step where it is idiomatic —
flattening nested FAERS JSON to Parquet — and kept **off the week-1 critical path**
so it cannot threaten the 7 Aug data-clean milestone. We state plainly that
DuckDB/dbt would suffice at this volume: **Spark is a deliberate skill
demonstration, not a technical necessity**, and we document that trade-off rather
than dress it up as a big-data requirement. This supersedes the prior-analysis
stance of rejecting Spark outright.

## Consequences
**Positive:** Demonstrable Spark competence on a real, idiomatic task; dbt keeps its
strengths; honest, defensible rationale (strong interview answer).

**Negative / accepted trade-offs:** One extra tool, ~1 day incl. Docker setup, and a
step DuckDB could do more simply. Accepted for the skill signal. Spark runs in
Docker (not native Windows) to avoid `winutils` friction.

**Revisit if:** week 1 slips → drop Spark, flatten in dbt/DuckDB, record it as a
deliberate scope cut. The flattening logic is engine-independent, so nothing else
changes.
