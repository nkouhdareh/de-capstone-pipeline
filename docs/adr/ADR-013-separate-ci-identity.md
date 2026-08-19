# ADR-013: A separate Snowflake identity for CI, not a second key on the production user

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-17 |
| **Deciders** | Nastaran Kouhdareh |

> *Recorded retrospectively. Implemented on 2026-08-17 as CI/CD phase 3
> (`.github/workflows/dbt-ci.yml`).*

## Context

The static CI gate (`ci.yml`) runs without any credentials — ruff, a syntax check, a
secret scan, `dbt parse` and pytest all work offline. But it cannot answer the question
that matters most: *do the models actually build?* `dbt parse` proves the Jinja and SQL
are syntactically valid; only `dbt build` proves the warehouse accepts them.

So CI needed to reach Snowflake. The pipeline already had a working service identity,
`DE_CAPSTONE_SVC`, whose key pair could simply have been added to GitHub Secrets and
pointed at a different schema.

That identity, however, **owns `DBT_DEV`** — the production marts — and holds `TRUNCATE`
and `INSERT` on the two `RAW` tables. Whatever CI ran as it would inherit that.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — A separate user `DE_CAPSTONE_CI` with its own key pair and 8 grants (chosen)** | Isolation becomes a **privilege** guarantee, not a configuration one; revocable independently; a leaked secret exposes only public FDA data and a throwaway schema | A second identity, key pair and grant set to create and maintain |
| B — Reuse `DE_CAPSTONE_SVC`, point CI at a `DBT_CI` schema | Nothing new to create; ready in minutes | Isolation rests on **one `schema:` line of YAML**. A typo, a bad merge or a wrong `--target` and CI overwrites the production marts. The identity has `TRUNCATE` on RAW, so a mistake could also empty the source tables |
| C — A second key pair on `DE_CAPSTONE_SVC` | Independently revocable key | Same privileges. Revoking the key limits *access*, not *blast radius*. The problem was never the key, it was what the user can do |
| D — No warehouse gate; keep CI offline-only | Zero credential surface | The most valuable check — that the models still build — never runs |

## Decision

We chose **A**. The distinction that drove it:

> With a shared identity, isolation is a **configuration** guarantee — one line of YAML.
> With a separate role, it is a **privilege** guarantee — a grant that does not exist.
> A profile typo returns a permission error instead of overwriting the marts.

`DE_CAPSTONE_CI` is `TYPE = SERVICE` with its own key pair (in `.keys-ci/`, separate from
the production key), and exactly **8 grants**:

| | `DE_CAPSTONE_CI` |
|---|---|
| Can read | `RAW.SILVER_DRUG_EVENT`, `RAW.DRUG_NDC` |
| Can build in | `DBT_CI` only (`USAGE` + `CREATE TABLE` + `CREATE VIEW`) |
| On `DBT_DEV` | **nothing** |
| On `RAW` | **read only** — no `INSERT`, no `TRUNCATE` |

**Proven, not asserted.** Acting as `DE_CAPSTONE_CI_ROLE`, `SELECT` on
`RAW.SILVER_DRUG_EVENT` succeeded (45,030,932 rows) and `SELECT` on `DBT_DEV.DIM_DRUG`
**failed with "not authorized"**. The boundary was tested from the inside, not inferred
from the grant list.

The same principle was applied on the AWS side: GitHub Actions authenticates by **OIDC**
with a short-lived token minted per job, into a role trusted only by this repository and
allowed only `ListBucket` and `GetObject` on one prefix — capped further by a permissions
boundary it cannot lift. **There is no AWS access key in the repository or in GitHub
Secrets.**

## Consequences

**Positive:** `dbt build --target ci` produces **PASS=53, WARN=0, ERROR=0 in 1 m 17 s** —
the same result production produces, reproduced by a different identity in a different
schema from a clean machine. That is a much stronger statement than "it works on my
laptop". If the GitHub secret leaked entirely, the worst case is that someone reads
**public FDA data** and scribbles in a throwaway schema. Revocation is surgical:
`DROP USER DE_CAPSTONE_CI` removes CI completely and leaves Airflow, both loaders and all
three dashboards working.

**Negative / accepted trade-offs:**

- Two key pairs, two users and two grant sets to maintain, and CI can drift from
  production if a new grant is added to one and not the other.
- Snowflake's privilege model made this fiddlier than expected, and the same lesson
  appeared three times: **privileges are not implied by ownership.** `CREATE STREAMLIT` is
  not implied by owning the schema; `ACCOUNTADMIN` could not read `DBT_CI` because
  *owning* a role is not being a *member* of it; `CREATE TABLE` needed its own grant.
- CI consumes a small amount of warehouse credit per run (~5 cents).

**Revisit if:** more environments appear (staging, a second developer). The pattern
generalises — one identity per environment, each with the minimum grants — but the grant
management would then justify managing Snowflake objects in Terraform rather than by hand
([ADR-014](ADR-014-terraform-ci-role-only.md) deliberately does not).
