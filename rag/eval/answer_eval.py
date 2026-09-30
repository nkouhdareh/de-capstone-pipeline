"""Phase 6, step 3: score whole answers on dev, one backend at a time.

Every dev question goes through the full pipeline (generate/answer.py). What is
counted needs no judge model:

  negatives    refused by the guardrail, refused by the model, or answered
               (the failure that matters: a confident answer with no source)
  answerable   answered, or wrongly refused, and by whom
  of answers   citation check passed; sentences uncited, citing a source that
               does not exist, or unsupported by what they cite
  grounded     the answer cites at least one chunk that holds the gold answer.
               Its ceiling is retrieval: a chunk not in the top 5 cannot be cited.
               A strict lower bound on being right: on the first full run, many
               correct answers cited another top-5 chunk stating the same fact
  states gold  the answer's text contains the gold answer's words: at least half
               of the gold span, weighted by BM25 idf and stemmed. A loose upper
               bound: it also passes "the sources do not mention X" when X is the
               gold span, and misses a right answer worded differently
  time         seconds per generated answer

The truth about how many answers are right lies between those two, and only a
person reading the answers can place it.

Answers are appended to a JSONL file as they finish, and a re-run skips the
questions already in it: the local model takes about a minute a question, so a
full dev run is over an hour and must survive an interruption.

Usage:
    python -m rag.eval.answer_eval --out D:/capstone/data/rag/answers/ollama-dev.jsonl
    python -m rag.eval.answer_eval --out ... --limit 5      # a first look
    python -m rag.eval.answer_eval --backend groq --out D:/capstone/data/rag/answers/groq-dev.jsonl

One file per backend: a file holds one backend's answers, and the run refuses
to add another backend's answers to it.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from rag.index.bm25_text import TOKEN, tokenize

STATES_GOLD = 0.5       # share of the gold span's weighted words an answer must contain


def cited_chunks(record: Mapping) -> set:
    """The chunk ids an answer's valid citations point at."""
    sources = record["sources"]
    return {sources[n - 1] for sentence in record["sentences"] for n in sentence["cited"]
            if 1 <= n <= len(sources)}


def span_recall(answer: str, span: str, stem: Callable[[str], str] | None = None,
                weight: Callable[[str], float] | None = None) -> float:
    """The share of the gold span's words found in the answer, by weight."""
    stem = stem or (lambda word: word)
    weight = weight or (lambda word: 1.0)
    said = {stem(word) for word in TOKEN.findall(answer.lower())}
    words = [stem(word) for word in tokenize(span)]
    total = sum(weight(word) for word in words)
    return sum(weight(word) for word in words if word in said) / total if total else 0.0


def summarise(records: Sequence[Mapping], relevant: Mapping[str, Iterable[str]],
              stated: Iterable[str] = ()) -> dict:
    """Counts over finished answers. records: the JSONL rows; relevant: qid ->
    the chunk ids that hold its gold answer (absent for negatives); stated: the
    qids whose answer text contains the gold span."""
    stated = set(stated)
    out: Counter = Counter()
    for record in records:
        negative = record["qid"] not in relevant
        kind = "negative" if negative else "answerable"
        out[kind] += 1
        refused = record["refused_by"]
        out[f"{kind} {'refused by ' + refused if refused else 'answered'}"] += 1
        if refused:
            continue
        out["answers"] += 1
        out["answers citation check ok"] += record["citations_ok"]
        for sentence in record["sentences"]:
            out["sentences"] += 1
            out["sentences uncited"] += not sentence["cited"]
            out["sentences invalid"] += bool(sentence["cited"]) and not sentence["valid"]
            out["sentences unsupported"] += (bool(sentence["cited"]) and sentence["valid"]
                                             and not sentence["supported"])
        if not negative:
            answers = set(relevant[record["qid"]])
            out["answerable with the answer in its sources"] += bool(answers & set(record["sources"]))
            out["answerable grounded"] += bool(answers & cited_chunks(record))
            out["answerable stating the gold answer"] += record["qid"] in stated
    return dict(out)


def to_record(qid: str, answer, min_support: float) -> dict:
    report = answer.report
    return {
        "qid": qid,
        "question": answer.question,
        "refused_by": answer.refused_by,
        "answer": answer.text,
        "sources": [source.chunk_id for source in answer.sources],
        "citations_ok": bool(report and report.ok and not report.refused),
        "sentences": [{"text": c.sentence, "cited": list(c.cited), "valid": c.valid,
                       "support": round(c.support, 3), "supported": c.support >= min_support}
                      for c in (report.checks if report else ())],
        "seconds": round(answer.seconds, 1),
        "backend": answer.generation.backend if answer.generation else None,
        "prompt_tokens": answer.generation.prompt_tokens if answer.generation else 0,
        "answer_tokens": answer.generation.answer_tokens if answer.generation else 0,
    }


def main() -> None:
    from rag.eval.ann_recall import percentile
    from rag.eval.gold import load_gold, resolve
    from rag.eval.run_eval import load_retriever
    from rag.generate.answer import Answerer, idf_weight
    from rag.generate.backends import make_backend
    from rag.generate.prompt import MIN_SUPPORT
    from rag.retrieve.guardrail import Guardrail
    from rag.retrieve.rerank import ChunkTexts

    parser = argparse.ArgumentParser(description="Score whole answers on dev.")
    parser.add_argument("--out", type=Path, required=True, help="JSONL of answers; appended to, resumable")
    parser.add_argument("--limit", type=int, default=0, help="only the first N questions")
    parser.add_argument("--backend", choices=("ollama", "groq"), default="ollama",
                        help="ollama: the local model; groq: the hosted one, needs GROQ_API_KEY in .env")
    args = parser.parse_args()

    questions = load_gold(split="dev")
    if args.limit:
        questions = questions[:args.limit]
    resolution = resolve(questions)
    done = {}
    if args.out.exists():
        with open(args.out, encoding="utf-8") as fh:
            done = {row["qid"]: row for row in map(json.loads, fh)}
    todo = [q for q in questions if q["qid"] not in done]
    print(f"{len(questions)} dev questions, {len(done)} already answered in {args.out.name}, {len(todo)} to go")

    loaded: dict = {}
    if todo:
        backend = make_backend(args.backend)
        others = {row["backend"] for row in done.values() if row["backend"]} - {backend.name}
        if others:
            raise SystemExit(f"{args.out} holds answers from {sorted(others)}; give {backend.name} its own file")
        retriever = load_retriever("hybrid-dedup", {}, loaded)
        answerer = Answerer(retriever, Guardrail(loaded["dense"], loaded["bm25"]), ChunkTexts(),
                            backend, stem=loaded["bm25"].stem, weight=idf_weight(loaded["bm25"]))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "a", encoding="utf-8") as fh:
            for n, question in enumerate(todo, start=1):
                record = to_record(question["qid"], answerer.answer(question["question"]), MIN_SUPPORT)
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                done[question["qid"]] = record
                print(f"  {n:>3}/{len(todo)} {question['qid']} {record['seconds']:>6.1f}s "
                      f"{record['refused_by'] or ('ok' if record['citations_ok'] else 'FLAGGED')}", flush=True)

    records = [done[q["qid"]] for q in questions if q["qid"] in done]
    sparse = loaded.get("bm25") or load_retriever("bm25", {}, loaded)
    weight = idf_weight(sparse)
    spans = {q["qid"]: q["anchor"]["answer_span"] for q in questions if q.get("anchor")}
    stated = [r["qid"] for r in records if r["qid"] in spans and not r["refused_by"]
              and span_recall(r["answer"], spans[r["qid"]], sparse.stem, weight) >= STATES_GOLD]
    counts = summarise(records, resolution.relevant, stated)
    used = next((r["backend"] for r in records if r["backend"]), "none")
    seconds = [r["seconds"] for r in records if r["backend"]]

    def line(label: str, key: str, of: str) -> None:
        print(f"  {label:<46} {counts.get(key, 0):>3} of {counts.get(of, 0)}")

    print(f"\nbackend: {used}")
    line("negatives refused by the guardrail", "negative refused by guardrail", "negative")
    line("negatives refused by the model", "negative refused by model", "negative")
    line("negatives ANSWERED", "negative answered", "negative")
    line("answerable answered", "answerable answered", "answerable")
    line("answerable wrongly refused by the guardrail", "answerable refused by guardrail", "answerable")
    line("answerable wrongly refused by the model", "answerable refused by model", "answerable")
    line("answers passing the citation check", "answers citation check ok", "answers")
    line("sentences with no citation", "sentences uncited", "sentences")
    line("sentences citing a source that does not exist", "sentences invalid", "sentences")
    line("sentences not supported by what they cite", "sentences unsupported", "sentences")
    line("answerable with the gold answer in the top 5", "answerable with the answer in its sources",
         "answerable answered")
    line("answerable grounded (cites a gold chunk)", "answerable grounded", "answerable answered")
    line("answerable stating the gold answer's words", "answerable stating the gold answer",
         "answerable answered")
    if seconds:
        print(f"  seconds per generated answer: p50 {percentile(seconds, 50):.0f}, p95 {percentile(seconds, 95):.0f}")


if __name__ == "__main__":
    main()
