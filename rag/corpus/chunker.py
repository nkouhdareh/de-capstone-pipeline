"""Section-aware chunker for openFDA SPL label text.

Pure functions only: no file I/O, no network, no corpus. The driver that
streams Bronze and writes Parquet lives in build_chunks.py, so this module
stays unit-testable in milliseconds.

Phase 0 measured two opposite problems in one corpus:

  Prescription sections are few and enormous. use_in_specific_populations
  overflows a 512-token window 94.6% of the time and warnings_and_cautions
  83.5%, needing 4.6 chunks on average.                          -> SPLIT

  OTC safety sections are six per label and tiny: stop_use 172 chars,
  when_using 157, do_not_use 169, ask_doctor 184. Roughly 40 tokens each.
  Embedded separately they carry too little context to match against.
                                                                 -> MERGE

One rule solves both: target ~400 tokens, split what is over, merge what is
under. TARGET is well clear of the 512-token cap because embedding quality
degrades near a model's limit, not only past it.
"""
from __future__ import annotations

import re
from functools import lru_cache

# The tokenizer that matters is the embedding model's own, since its 512-token
# limit is what the chunk has to fit. Phase 3 may swap the model; changing this
# constant re-chunks the corpus, which is why chunker_version is recorded.
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
CHUNKER_VERSION = "1.0.0"

TARGET_TOKENS = 400   # aim here
MAX_TOKENS = 480      # never exceed; the model cap is 512
MIN_TOKENS = 30       # below this a chunk is noise, not signal
CHARS_PER_TOKEN = 4   # only used if the real tokenizer is unavailable

# Nine prescription-oriented sections plus `warnings`, which both label types
# use. Split when they overflow, keep whole when they do not: contraindications
# overflows only 3.2% of the time, so splitting it by default would be wrong.
RX_SECTIONS = (
    "boxed_warning",
    "adverse_reactions",
    "warnings",
    "warnings_and_cautions",
    "contraindications",
    "drug_interactions",
    "indications_and_usage",
    "use_in_specific_populations",
    "dosage_and_administration",
    "overdosage",
)

# The OTC Drug Facts safety panel, in the order it appears on a carton.
# Merged into a single chunk per label.
OTC_SAFETY_GROUP = (
    "do_not_use",
    "ask_doctor",
    "ask_doctor_or_pharmacist",
    "when_using",
    "stop_use",
    "other_safety_information",
)

# Human-readable prefixes, so a merged chunk stays legible about which
# regulatory field each sentence came from.
OTC_FIELD_LABELS = {
    "do_not_use": "Do not use",
    "ask_doctor": "Ask a doctor before use if",
    "ask_doctor_or_pharmacist": "Ask a doctor or pharmacist before use if",
    "when_using": "When using this product",
    "stop_use": "Stop use and ask a doctor if",
    "other_safety_information": "Other safety information",
}

OTC_GROUP_NAME = "otc_safety_panel"
ALLOWLIST = RX_SECTIONS + OTC_SAFETY_GROUP

_INLINE_WS = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_PARAGRAPH = re.compile(r"\n\s*\n+")
# Split on whitespace after terminal punctuation, when what follows starts a
# new sentence (optional opening quote or bracket, then a capital or digit).
# Decimals are safe because "2.5" has no whitespace after the period, and
# abbreviations are safe because their periods are masked before this runs.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"\'(\[]?[A-Z0-9])")


def normalise_whitespace(text: str) -> str:
    """Collapse runs of spaces but preserve paragraph breaks, which are the
    first split boundary and therefore load-bearing."""
    if not text:
        return ""
    return _BLANK_LINES.sub("\n\n", _INLINE_WS.sub(" ", text)).strip()


@lru_cache(maxsize=1)
def _load_tokenizer(model_id: str):
    """None if tokenizers or the model is unavailable, so the chunker still
    runs offline on a character estimate rather than failing outright."""
    try:
        from tokenizers import Tokenizer
        return Tokenizer.from_pretrained(model_id)
    except Exception:  # noqa: BLE001 - any failure means fall back, deliberately
        return None


def token_counter(model_id: str = EMBED_MODEL, cache_size: int = 8192):
    """Return a callable text -> token count.

    Counts with the embedding model's own tokenizer so the number means what
    the model will actually see. Callers rely on one precondition, which every
    real tokenizer satisfies: a token is never fewer than one character, so
    len(text) <= cap implies count(text) <= cap. Falls back to chars/4, which is close enough
    for English prose to keep the pipeline running but must not be trusted for
    the 512-token gate.
    """
    tok = _load_tokenizer(model_id)
    if tok is None:
        def _count(text: str) -> int:
            return max(1, len(text) // CHARS_PER_TOKEN)
    else:
        def _count(text: str) -> int:
            return len(tok.encode(text, add_special_tokens=False).ids)
    # atomize measures every unit, then pack measures the same units again.
    # Caching turns that second pass into hits: hashing a 2 KB string costs
    # microseconds, tokenizing it costs roughly 100x more.
    return lru_cache(maxsize=cache_size)(_count)


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH.split(text) if p.strip()]


# pysbd knows prose abbreviations ("e.g.", "Dr.") but not the unit and dosing
# abbreviations that fill label text, and splits after "5 mg." or "approx.".
# Masking the trailing period before segmentation costs ten lines and prevents
# "Do not exceed 10 mg." being severed from "per day".
_ABBREVIATIONS = (
    "approx", "b.i.d", "t.i.d", "q.i.d", "p.r.n", "Corp", "q.d", "p.o",
    "i.v", "i.m", "e.g", "i.e", "U.S", "mEq", "mcg", "Inc", "Ltd",
    "mL", "ml", "mg", "kg", "IU", "oz", "fl", "vs", "Co", "Dr", "St", "No", "g",
)
_PERIOD_MASK = "\uE000"          # private-use codepoint; pysbd will not split on it
_ABBREV_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in
                      sorted(_ABBREVIATIONS, key=len, reverse=True)) + r")\."
)


def split_sentences(text: str) -> list[str]:
    """Sentence-split, masking clinical abbreviations so they are not read as
    sentence ends.

    This replaced pysbd, which was 50% of total runtime: its abbreviation
    replacer compiled patterns dynamically per abbreviation per text, 988,976
    re compilations for 347 labels, blowing Python's pattern cache. It was also
    doing work already done here, since _ABBREV_RE masks the periods before it
    ever sees them, and it did not know unit abbreviations anyway.
    """
    masked = _ABBREV_RE.sub(lambda m: m.group(1) + _PERIOD_MASK, text)
    parts = _SENTENCE_SPLIT.split(masked)
    return [p.replace(_PERIOD_MASK, ".").strip() for p in parts if p and p.strip()]


def _measured_split(text: str, count_tokens, hard_max: int) -> list[str]:
    """Split on word boundaries using MEASURED token counts, never an estimate.

    A word-ratio estimate is unsafe on this corpus. Ordinary English runs about
    1.3 tokens per word, but "hydrochlorothiazide", "carcinogenesis" and
    "thrombocytopenia" break into many subword pieces, pushing label text near
    3 tokens per word. An earlier version assumed 1.4 and emitted chunks of
    1,045 tokens against a 480 cap.

    O(n) tokenizer calls on a growing string, so quadratic in total work. That
    is acceptable because this is the rare path: it runs only for a single
    sentence longer than the whole window.
    """
    out: list[str] = []
    current: list[str] = []
    for word in text.split():
        trial = current + [word]
        if current and count_tokens(" ".join(trial)) > hard_max:
            out.append(" ".join(current))
            current = [word]
        else:
            current = trial
    if current:
        out.append(" ".join(current))
    return out


def atomize(text: str, count_tokens, hard_max: int = MAX_TOKENS) -> list[str]:
    """Break text into units none of which exceeds hard_max tokens.

    Paragraph first because a paragraph is a complete argument; sentence only
    when a paragraph is too long; words only when a sentence is.
    """
    units: list[str] = []
    for para in split_paragraphs(text):
        if len(para) <= hard_max or count_tokens(para) <= hard_max:
            units.append(para)
            continue
        for sent in split_sentences(para):
            if len(sent) <= hard_max or count_tokens(sent) <= hard_max:
                units.append(sent)
            else:
                units.extend(_measured_split(sent, count_tokens, hard_max))
    return units


def pack(units, count_tokens, target: int = TARGET_TOKENS,
         hard_max: int = MAX_TOKENS, joiner: str = "\n\n") -> list[str]:
    """Greedily fill windows: flush at target, never exceed hard_max.

    Greedy rather than balanced because retrieval cares that a chunk is
    coherent and within the window, not that chunks are equal sizes.
    """
    chunks, current, size = [], [], 0
    for unit in units:
        n = count_tokens(unit)
        if current and size + n > hard_max:
            chunks.append(joiner.join(current))
            current, size = [], 0
        current.append(unit)
        size += n
        if size >= target:
            chunks.append(joiner.join(current))
            current, size = [], 0
    if current:
        chunks.append(joiner.join(current))
    return chunks


def chunk_section(text: str, count_tokens=None, target: int = TARGET_TOKENS,
                  hard_max: int = MAX_TOKENS,
                  min_tokens: int = MIN_TOKENS) -> list[str]:
    """Chunk one section. Returns [] when the text is too short to be useful."""
    count_tokens = count_tokens or token_counter()
    text = normalise_whitespace(text)
    if not text:
        return []
    # No character fast path here: the min_tokens floor below needs a real count
    # for exactly the short texts a length check would skip, so it would buy
    # nothing and would silently keep sections that belong dropped. The cached
    # counter already makes the repeat measurement in emit() free.
    total = count_tokens(text)
    if total < min_tokens:
        return []
    if total <= hard_max:
        return [text]                       # keep-whole path
    chunks = pack(atomize(text, count_tokens, hard_max),
                  count_tokens, target, hard_max)
    # A stub tail is worse than a slightly longer final chunk: fold it back.
    if len(chunks) > 1 and count_tokens(chunks[-1]) < min_tokens:
        tail = chunks.pop()
        chunks[-1] = chunks[-1] + "\n\n" + tail
    # Enforce the cap last and unconditionally. Upstream splitting can overshoot
    # (a single oversized unit, or the tail fold above); this is the invariant
    # the whole design exists to protect, so it is checked rather than assumed.
    enforced: list[str] = []
    for chunk in chunks:
        if len(chunk) <= hard_max or count_tokens(chunk) <= hard_max:
            enforced.append(chunk)
        else:
            enforced.extend(_measured_split(chunk, count_tokens, hard_max))
    return enforced


def merge_otc_safety(sections: dict) -> str:
    """Concatenate the OTC Drug Facts safety fields into one text.

    Each field keeps a human-readable prefix so provenance survives the merge:
    a retrieved chunk still shows which regulatory field a warning came from.
    """
    parts = []
    for name in OTC_SAFETY_GROUP:
        body = normalise_whitespace(sections.get(name) or "")
        if body:
            parts.append(f"{OTC_FIELD_LABELS[name]}: {body}")
    return "\n\n".join(parts)


def context_header(drug: str, brand: str, manufacturer: str, section: str,
                   part_i: int, part_n: int) -> str:
    """Deterministic contextual-retrieval header, built from metadata rather
    than generated by an LLM, so it costs zero inference.

    Fixes the orphan-chunk failure: "the most common reactions were nausea and
    headache" is unretrievable when the chunk never names its drug.
    """
    head = f"Drug: {drug or 'Unknown'}"
    if brand and brand.upper() != (drug or "").upper():
        head += f" (brand {brand})"
    if manufacturer:
        head += f" | Manufacturer: {manufacturer}"
    part = f" | Part {part_i} of {part_n}" if part_n > 1 else ""
    return f"{head}\nSection: {section}{part}"
