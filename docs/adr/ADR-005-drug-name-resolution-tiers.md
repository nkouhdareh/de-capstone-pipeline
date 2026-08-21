# ADR-005: Tiered exact matching for drug resolution; fuzzy matching rejected

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-07 |
| **Deciders** | Nastaran Kouhdareh |

## Context

FAERS reports carry free-text drug names. The same substance appears as `TYLENOL`,
`Tylenol 500mg`, `ACETAMINOPHEN`, `PARACETAMOL` and `TYLNOL`. There are **97,789
distinct raw product names** across 10.4 million drug rows, which the warehouse's
intermediate layer reduces to **84,038 distinct drug signatures**.

This matters more than it looks. PRR and ROR are ratios of case counts. If one drug's
cases fragment across five name variants, every one of those variants gets a case count
too low to clear the thresholds, and a real signal disappears. Conversely, merging two
drugs that are not the same manufactures a signal that does not exist.

The FDA's own NDC directory (136,520 products) is the reference, but it is itself
imperfect — it contains both `ZINC OXIDE` and `ZINCOXIDE`, and it contains
`ACETAMINOPHEN ASPRIN CAFFEINE` with *aspirin* misspelled.

This was identified up front as the highest-risk component of the project: unbounded in
effort and directly upstream of every number.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Tiered exact matching: `rxcui` → generic name → brand name → active ingredient, ambiguity left unresolved (chosen)** | Bounded effort, roughly one day; every match is defensible; failure is visible and countable rather than silent; runs once per distinct signature rather than per row | Leaves a long tail unresolved — 10.0 % of distinct signatures match, though these cover 86.7 % of rows |
| B — Fuzzy matching (trigram / Levenshtein / edit distance) | Higher headline resolution rate; catches obvious typos like `TYLNOL` | **Actively dangerous for drug names.** WHO nomenclature deliberately gives drugs in the same class near-identical endings — every proton-pump inhibitor ends `-prazole`, every monoclonal antibody ends `-mab`. `Lansoprazole` and `Pantoprazole` are two characters apart and are different drugs. Effort is unbounded, and every candidate still needs a human to judge it |
| C — Manual curation of the top N drugs | Perfect accuracy where applied | Does not scale past a few hundred; the tail is where the fragmentation lives; not reproducible |
| D — Drop unresolved rows entirely | Clean dimension | Silently deletes ~13 % of the fact table and biases every denominator. The rows are evidence; discarding them is how pipelines lie |

## Decision

We chose **A**, with the governing principle stated explicitly in the model:

> **An unknown drug is better than a wrong drug.**

Matching runs in four tiers, most reliable first — `rxcui` (a numeric code, no typo
surface), then normalised generic name, then brand name, then active ingredient.
Normalisation uppercases, strips dosage strings, salt forms and punctuation, and
collapses whitespace. Only **exact** matches on the normalised value are accepted. If one
`rxcui` maps to two different generic names, the mapping is rejected rather than guessed.

Anything still unmatched keeps `drug_key = -1` (Unknown), is **counted, not dropped**,
and is **excluded from the PRR/ROR models** — an unidentified drug cannot be scored, but
its rows remain in the atomic fact for auditing.

Resolution executes once per distinct signature (84,038) rather than once per row
(45,030,932): the same answer at a fraction of the cost.

**Two resolution rates are published, because they answer different questions:**
**86.7 % of rows** resolve, but only **10.0 % of distinct signatures**. Common drugs
resolve; a long tail of typos and one-off names does not. The row-level figure is the one
that matters, because the statistics are computed over rows.

## Consequences

**Positive:** A measured, defensible number instead of an unbounded effort. Every drug
identity in `dim_drug` (4,368 entries) can be traced to an exact match on a named tier.
The headline signals are unaffected by the unresolved tail — a later audit confirmed that
the top-ranked results are limited by **interpretation**, not by name resolution, which
retrospectively validates the decision not to spend more time here.

**Negative / accepted trade-offs:** The 10 % signature-level rate looks poor out of
context and invites the question every time it is shown. Roughly 40 duplicate spellings
survive in `dim_drug` because the FDA's own directory contains them — measured at under
4,000 fact rows, i.e. under 0.01 %, and left unfixed rather than rebuilding the warehouse
days before delivery. A larger known issue is that normalisation strips mineral salts, so
`sodium chloride` and `calcium chloride` both collapse to `CHLORIDE` — roughly 350,000
rows under names that are not drugs. This wrongly *merges* rather than splits, which is
worse, and it is documented rather than fixed for the same reason.

**Revisit if:** the drug dimension is rebuilt for any other reason — the salt-stripping
fix is one line in `normalize_drug_name`, but it regenerates every `drug_key` and
therefore every documented figure in the project.
