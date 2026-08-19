# Architecture Decision Records

Every significant technical decision gets a short record: what was decided, what was
rejected, and why. The capstone evaluation criteria weight *"the maintenance of your
ADRs"* alongside the other documentation, so these are graded, not optional.

## Rules

1. **Write the ADR when you make the decision**, not at the end of the project.
   Reconstructed reasoning is obvious and unconvincing.
2. **Always record what you rejected.** An ADR with no alternatives considered is
   not a decision, it is a preference.
3. **Keep them short** — half a page. If it needs more, it is two decisions.
4. **Never delete one.** If a decision changes, add a new ADR that supersedes it.
   The change of mind is itself evidence of engineering judgement.

Rule 1 was not honoured consistently. ADRs 001, 002 and 004 were written at decision time
on 2026-08-02/03; the rest were written on 2026-08-19 from the build log and the working
notes in `docs/Layer Explanation/`. Those records say so at the top rather than pretending
otherwise, and each names the date the decision was actually taken.

## Naming

`ADR-NNN-short-kebab-title.md`, numbered in the order decided.

Numbers 003, 005, 006, 007, 008 and 009 were **reserved** in `architecture.md` on
2026-08-02 before they were written. Each reserved number kept its original meaning, so
that references written against it elsewhere in the repository stay valid. Numbers 006 and
008 were reserved for component choices inside the retrieval extension; that extension was
never built, so the decisions were never taken and the numbers stay unused —
[ADR-015](ADR-015-retrieval-extension-not-built.md) supersedes them.

## Index

| ADR | Decision | Status | Decided |
|---|---|---|---|
| [000](ADR-000-template.md) | Template | — | — |
| [001](ADR-001-domain-and-data-source.md) | Domain and data source — openFDA drug safety | Accepted | 2026-08-02 |
| [002](ADR-002-warehouse-snowflake.md) | Snowflake as the data warehouse | Accepted | 2026-08-02 |
| [003](ADR-003-medallion-layering.md) | Medallion layering rather than Data Vault | Accepted | 2026-08-02 |
| [004](ADR-004-dbt-and-spark-transformation.md) | dbt for modelling, PySpark for flattening | Accepted | 2026-08-02 |
| [005](ADR-005-drug-name-resolution-tiers.md) | Tiered exact matching for drug resolution; fuzzy matching rejected | Accepted | 2026-08-07 |
| 006 | *Vector store — reserved, never decided* | Superseded by [015](ADR-015-retrieval-extension-not-built.md) | — |
| [007](ADR-007-no-streaming-layer.md) | No streaming layer — batch ELT only | Accepted | 2026-08-02 |
| 008 | *Generation model — reserved, never decided* | Superseded by [015](ADR-015-retrieval-extension-not-built.md) | — |
| [009](ADR-009-hybrid-deployment-bronze-local.md) | Hybrid deployment — Bronze stays on local disk | Accepted | 2026-08-03 |
| [010](ADR-010-airflow-triggers-containers.md) | Airflow triggers Spark and dbt in their own containers | Accepted | 2026-08-11 |
| [011](ADR-011-s3-external-stages.md) | S3 external stages replace Snowflake internal stages | Accepted | 2026-08-12 |
| [012](ADR-012-snowflake-key-pair-service-identity.md) | Key-pair authentication with a `TYPE = SERVICE` identity | Accepted | 2026-08-13 |
| [013](ADR-013-separate-ci-identity.md) | A separate Snowflake identity for CI | Accepted | 2026-08-17 |
| [014](ADR-014-terraform-ci-role-only.md) | Terraform scoped to the CI IAM role only | Accepted | 2026-08-17 |
| [015](ADR-015-retrieval-extension-not-built.md) | The retrieval (RAG) extension was not built | Accepted | 2026-08-18 |

## Where the reasoning came from

The retrospective ADRs draw on the working record kept during the build — the phase guides
in `docs/Layer Explanation/` (git-ignored, local only), the running log in
`docs/PROGRESS.md`, and the failure playbook in `runbook.md`. Nothing in them was invented
after the fact; each decision is traceable to a dated commit or a recorded incident.
