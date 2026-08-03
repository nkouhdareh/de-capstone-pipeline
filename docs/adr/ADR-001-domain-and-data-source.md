# ADR-001: Domain and data source — openFDA drug safety (FAERS)

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-02 |
| **Deciders** | Nastaran Kouhdareh |

## Context
The capstone is graded on data-engineering craft, and the rubric rewards messy,
high-surface-area data over a polished business story. I need an open, licence-clear
source that is accessible immediately — no credentialing or approval waits (the
Arbeitsagentur API already burned me with a 401) — that I can clean, model, and
defend, ideally aligned with my medical background so I can judge whether the output
is correct.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — openFDA drug safety: `drug/event` (FAERS) + `drug/label` + `drug/ndc` (chosen)** | Public, keyless, US-Gov public-domain licence; 20M+ nested/coded records → rich cleaning, dedup and entity-resolution surface; free-text labels give the RAG extension a real home; aligns with my pharma/medical background | Batch only (no native streaming); MedDRA/coded fields need domain care |
| B — German electricity (SMARD / ENTSO-E) | Near-real-time; genuine streaming story; very "German" | Cleaner data (less cleaning to show); no text for RAG; a previous cohort already built it |
| C — Aviation (OpenSky) / news (GDELT) | Streaming (OpenSky) or volume + text (GDELT) | OpenSky access uncertain; GDELT is a firehose (scope risk); weaker domain fit for me |

## Decision
We chose **A**. openFDA scores highest on the axes the rubric rewards — messiness,
nesting, deduplication, entity resolution, volume, licence, and a genuine
unstructured-text corpus for retrieval — and it lets me use domain knowledge as a
data-quality capability. We accept losing a native streaming story (see ADR-007)
because batch is rubric-acceptable and the cleaning/governance surface is stronger.
A real `drug/event` record was pulled live on 2026-08-02, and the choice will be
stress-tested by a hands-on data probe before the architecture gate.

## Consequences
**Positive:** High engineering surface area; defensible domain expertise; fully
publishable repo and demo; RAG has a non-contrived home (drug labels).

**Negative / accepted trade-offs:** No real-time layer; the MedDRA dictionary is
licensed, so only FDA-published reaction terms are used and the dictionary itself is
never redistributed.

**Revisit if:** openFDA access degrades (fall back to the quarterly bulk files), or
the probe shows the cleaning surface is thinner — or the data nastier — than
workable → reassess against Candidate B.
