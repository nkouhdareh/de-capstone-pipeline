# ADR-002: Snowflake as the data warehouse

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-02 |
| **Deciders** | Nastaran Kouhdareh |

## Context
The medallion silver/gold layers and the star-schema serving marts need an
analytical warehouse that dbt can build into. Constraints: 3-week timeline; ~$182
AWS credits but $0 Snowflake beyond a one-month free trial; the choice must clear an
architecture gate and be demonstrable. Showcasing a cloud data warehouse is an
explicit portfolio goal for me.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Snowflake (chosen)** | Cloud-DWH skill I want to demonstrate; matches the cohort pattern instructors assess; ~$2 observed cost; already used in week-5 (known to me) | One-month trial → repo unrunnable after expiry; external-stage/IAM setup overhead |
| B — DuckDB | Free forever, fast, dbt-native, clean-clone runnable indefinitely | Not a cloud DWH; lower skill signal |
| C — Postgres | Free; already running for Airflow / pgvector | Heavier for analytical scans; no warehouse-skill signal |

## Decision
We chose **Snowflake**, because demonstrating a cloud data warehouse is a deliberate
portfolio goal, it matches the reference architecture the instructors know how to
grade, and the observed ~$2 cost sits well inside the one-month trial that fully
covers the 3–24 Aug window. dbt keeps the models engine-portable, so the decision
stays reversible.

## Consequences
**Positive:** Industry-relevant cloud-DWH experience; alignment with the cohort
house pattern; direct reuse of the week-5 Snowflake + dbt + Airflow setup.

**Negative / accepted trade-offs:** The public repo stops running when the trial
expires (~early Sept), so later portfolio demos need a live trial or a warehouse
swap; some external-stage/IAM setup cost. Accepted because the project window is
covered and the demonstration is the point.

**Revisit if:** the trial is at risk mid-project, or long-term runnability becomes a
priority → swap the dbt target to DuckDB/Postgres. To keep that a profile change and
not a rewrite, SQL stays engine-portable (`dbt_utils` macros, no Snowflake-only
functions). Also revisit per coach guidance.
