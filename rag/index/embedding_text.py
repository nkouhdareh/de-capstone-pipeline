"""What the embedding model actually reads, for chunks and for questions.

Kept apart from build_index.py and dense.py so both use the same rules, and so
the tests need no model, no numpy and no network: CI installs only pytest.

Two rules, both measured rather than assumed:

1. A chunk is embedded with a compact header: drug, brand and section. Phase 1's
   full header also names the manufacturer and "Part 2 of 5", which help nobody
   find anything. At 30 tokens on average and 237 at worst (a homeopathic remedy
   listing 20 ingredients as its drug name), it pushed 2,732 chunks (0.76%) past
   the model's window, where the model silently drops the end. Here the drug
   names are trimmed until the whole text fits, so the model never cuts a chunk.
   The brand stays: some identifier questions find their chunk only through it.

2. A question carries arctic's instruction, a chunk carries nothing. fastembed
   does not add it: for this model its query_embed() is plain embed(), read from
   its source on 2026-09-24. So this module adds it, and a test pins the exact
   string from the model card. Getting it wrong costs recall and raises no error.
"""
from __future__ import annotations

MODEL_ID = "snowflake/snowflake-arctic-embed-s"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
TOKEN_LIMIT = 510          # the model's 512, minus the [CLS] and [SEP] it adds itself
HEADER_VERSION = "compact-v1"
TRIMMED = "..."


def section_title(section: str) -> str:
    return section.replace("_", " ").title()


def drug_names(generic: str | None, brand: str | None) -> str:
    drug = generic or brand or "Unknown"
    if brand and brand.upper() != drug.upper():
        return f"{drug} (brand {brand})"
    return drug


def passage_text(text: str, generic: str | None, brand: str | None, section: str,
                 count_tokens, limit: int = TOKEN_LIMIT) -> str:
    """The chunk as the model reads it: compact header, blank line, chunk text.

    Only the drug names are ever shortened, never the chunk text, which is the
    part that holds the answer. A chunk too long on its own is refused, because
    that means the chunker's 480-token cap was broken upstream.
    """
    names = drug_names(generic, brand)
    tail = f"\nSection: {section_title(section)}\n\n{text}"
    whole = f"Drug: {names}{tail}"
    if count_tokens(whole) <= limit:
        return whole

    def trimmed(n: int) -> str:
        return f"Drug: {names[:n].rstrip()}{TRIMMED}{tail}"

    if count_tokens(trimmed(0)) > limit:
        if count_tokens(text) > limit:
            raise ValueError(f"chunk alone is over {limit} tokens: the chunker's cap was broken")
        return text
    # Longest prefix of the names that still fits. trimmed(lo) always fits.
    lo, hi = 0, len(names)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(trimmed(mid)) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return trimmed(lo)


def query_text(question: str) -> str:
    return QUERY_PREFIX + question
