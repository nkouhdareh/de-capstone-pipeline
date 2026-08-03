# Architecture Decision Records

Every significant technical decision gets a short record: what was decided, what was
rejected, and why. My coach's rubric weights *"explaining why you made those choices"*
as heavily as the build itself, so these are graded, not optional.

## Rules

1. **Write the ADR when you make the decision**, not at the end of the project.
   Reconstructed reasoning is obvious and unconvincing.
2. **Always record what you rejected.** An ADR with no alternatives considered is
   not a decision, it is a preference.
3. **Keep them short** — half a page. If it needs more, it is two decisions.
4. **Never delete one.** If a decision changes, add a new ADR that supersedes it.
   The change of mind is itself evidence of engineering judgement.

## Naming

`ADR-NNN-short-kebab-title.md`, numbered in the order decided.

## Index

| ADR | Decision | Status | Date |
|---|---|---|---|
| [000](ADR-000-template.md) | Template | — | — |
| [001](ADR-001-domain-and-data-source.md) | Domain & data source — openFDA drug safety | Accepted | 2026-08-02 |
| [002](ADR-002-warehouse-snowflake.md) | Snowflake as the data warehouse | Accepted | 2026-08-02 |
| [004](ADR-004-dbt-and-spark-transformation.md) | dbt for modelling + PySpark for flattening | Accepted | 2026-08-02 |

*Add a row each time you write one. (ADR-003 and 005–009 are reserved in `architecture.md` and will be written as each is locked.)*
