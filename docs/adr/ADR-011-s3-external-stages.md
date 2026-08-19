# ADR-011: S3 external stages replace Snowflake internal stages

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-12 |
| **Deciders** | Nastaran Kouhdareh |

> *Recorded retrospectively. The external stages were configured and validated on
> 2026-08-09 and production was cut over on 2026-08-12.*

## Context

The first working load path used **Snowflake internal stages**: `scripts/load_to_snowflake.py`
`PUT`s local Parquet into `@RAW.SILVER_STAGE`, then `COPY INTO` loads it. It worked, it
was simple, and it loaded all 45,030,932 rows.

TR-09 specified an **external stage over cloud object storage** with a storage
integration. Continuing with internal stages would have been a documented deviation from
the technical requirements.

The load path also sat directly upstream of every number in the project, so any change to
it had to be provably non-destructive.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — S3 external stage with a Snowflake storage integration (chosen)** | Silver becomes an **independent artifact** that Spark, Athena or a second warehouse could read; inspectable and baselinable with `aws s3 ls` before a destructive run; `aws s3 sync` is parallel, resumable and can mirror with `--delete`; storage integration means **no AWS keys stored in Snowflake**; satisfies TR-09 | External-stage and IAM setup cost; a second identity to manage; **no speed benefit whatsoever** |
| B — Keep internal stages | Already working; zero further setup | Silver exists only inside Snowflake. `PUT` is one file at a time through the Snowflake client, not resumable and not parallel. No way to inspect or baseline the artifact. Documented deviation from TR-09 |
| C — Load directly from local disk into Snowflake with no stage abstraction | Fewest moving parts | Same limitations as B, and no rollback path once the loader changes |

## Decision

We chose **A**, and the honest framing matters:

> **S3 did not make loading faster.** Either way the 3.9 GB travels from the laptop over
> the internet — the same network hop. The benefit is architectural, not performance.

What it actually bought:

1. **Separation of storage from compute.** In an internal stage, Silver exists only as
   something Snowflake happens to hold. In S3 it is an artifact in its own right.
2. **An artifact you can inspect.** `aws s3 ls --summarize` gives an object count and a
   byte total, which became the safety baseline captured before every destructive run —
   and later the basis of an automated CI gate asserting **486 objects /
   3,913,635,942 bytes**.
3. **Better upload mechanics.** `sync --delete` mirrors a prefix; `PUT` cannot.
4. **No credentials in Snowflake.** The storage integration uses an IAM role assumed by
   Snowflake, scoped read-only to the `silver/` and `ndc/` prefixes.
5. **Cost.** S3 storage is cheaper than Snowflake stage storage and supports lifecycle
   rules.

The bucket region was verified against Snowflake's with `CURRENT_REGION()` before
anything was created — same-region traffic is free, and a bucket in `us-east-1` would have
cost egress on every load *and* run slower.

**The cutover was made provably safe.** Before touching production, the S3 path was loaded
into a temporary table and compared three ways against the live table: total row count
(**45,030,932 = 45,030,932**), a known month, and a **`MINUS` on the grain key, which
returned 0**. Equal counts alone prove nothing; the `MINUS` proves the rows are identical
rather than merely equinumerous. Only then was `TRUNCATE` + `COPY` run against production,
and the acceptance check was that **clozapine → neutropenia stayed at PRR 35.94** — same
inputs, same maths, same answer, different infrastructure.

**The internal stages and `load_to_snowflake.py` were deliberately kept intact** as the
rollback path, and were migrated to key-pair authentication along with everything else.
A rollback is only worth claiming if it still runs.

## Consequences

**Positive:** TR-09 satisfied. Silver is an inspectable artifact, which directly enabled
the `s3-contract.yml` CI gate and the before/after baselines around the destructive
24-month run. The protected fallback prefix (`silver/drug_event/`) and the pipeline's own
prefix (`silver_pipeline/`) differ by **2,698 bytes** of Parquet metadata across 3.9 GB —
itself evidence the two copies are the same data.

**Negative / accepted trade-offs:**

- Two Silver copies in S3 while both exist, roughly doubling that prefix's storage.
- Adding an S3 prefix now means editing **two** policies — the uploader's and Snowflake's
  reader — which is easy to half-do.
- The `upload_s3` task introduced a genuine bug that internal stages could not have had:
  `aws s3 sync` **without `--delete` only adds**, and Spark names output with a per-run
  UUID, so an earlier run's 13 files survived alongside 486 new ones. Unfixed, the next
  load would have inserted **46,580,195** rows — January twice — and silently corrupted
  every PRR. *The Spark job was idempotent; the upload task was not. Idempotency is a
  property of the whole chain.* Fixed with `sync --delete` plus `s3:DeleteObject` scoped
  to `silver_pipeline/*` only, so the pipeline can mirror the prefix it owns while the
  validated artifact stays physically undeletable.

**Revisit if:** Bronze ever moves to S3 as well ([ADR-009](ADR-009-hybrid-deployment-bronze-local.md)),
at which point the same integration extends by an `ALTER` on the allowed locations — which
does not rotate the external id, so no trust-policy rework is needed.
