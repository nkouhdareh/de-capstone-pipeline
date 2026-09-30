"""Unit tests for the answer pipeline and its evaluation's counting. Fakes stand
in for retrieval, the guardrail and the model, so CI runs these."""
from rag.eval.answer_eval import cited_chunks, summarise, to_record
from rag.generate.answer import Answerer, idf_weight, refusal_text
from rag.generate.backends import Generation
from rag.generate.prompt import MIN_SUPPORT, REFUSAL
from rag.retrieve.guardrail import Verdict

TEXTS = {"c1": "PANTOPRAZOLE\nWarnings\nHypomagnesemia has been reported with PPIs.",
         "c2": "PANTOPRAZOLE\nAdverse Reactions\nHeadache and diarrhea were common."}
QUESTION = "Does pantoprazole cause low magnesium?"


class FakeRetriever:
    def search(self, question, k):
        return ["c1", "c2"][:k]


class FakeGuardrail:
    def __init__(self, verdict):
        self.verdict = verdict

    def check(self, question):
        return self.verdict


class FakeBackend:
    name = "fake"

    def __init__(self, text):
        self.text, self.prompts = text, []

    def generate(self, system, user):
        self.prompts.append(user)
        return Generation(self.text, 1.5, 100, 10, self.name)


OK = Verdict(True, "ok", (), 0.80)


def answerer(text, verdict=OK):
    backend = FakeBackend(text)
    return Answerer(FakeRetriever(), FakeGuardrail(verdict), TEXTS, backend), backend


def test_the_guardrail_refuses_without_calling_the_model():
    pipeline, backend = answerer("unused", Verdict(False, "unknown words", ("gliclazide",), 0.75))

    answer = pipeline.answer("What is the dose of gliclazide?")

    assert answer.refused_by == "guardrail" and "gliclazide" in answer.text
    assert backend.prompts == [] and answer.sources == () and answer.report is None


def test_refusal_text_for_low_similarity_names_no_word():
    assert "close enough" in refusal_text(Verdict(False, "low similarity", (), 0.61))


def test_an_answer_carries_its_numbered_sources_and_a_citation_report():
    pipeline, backend = answerer("Hypomagnesemia has been reported [1].")

    answer = pipeline.answer(QUESTION)

    assert answer.refused_by is None and answer.report.ok
    assert [source.chunk_id for source in answer.sources] == ["c1", "c2"]
    assert "[1] PANTOPRAZOLE" in backend.prompts[0] and QUESTION in backend.prompts[0]


def test_the_models_own_refusal_is_told_apart_from_the_guardrails():
    pipeline, _ = answerer(f"Nothing relevant was found [1]. {REFUSAL}")

    assert pipeline.answer(QUESTION).refused_by == "model"


class FakeIdf(list):
    def max(self):
        return max(self)


class FakeSparse:
    def __init__(self):
        self.term_id = {"patient": 0, "alopecia": 1}
        self.idf = FakeIdf([0.5, 8.0])


def test_idf_weight_gives_an_unknown_word_the_highest_weight():
    weight = idf_weight(FakeSparse())

    assert (weight("patient"), weight("alopecia"), weight("zzz")) == (0.5, 8.0, 8.0)


def record(qid, refused_by=None, sources=("c1", "c2"), cited=(1,), ok=True):
    return {"qid": qid, "refused_by": refused_by, "sources": list(sources), "citations_ok": ok,
            "sentences": [] if refused_by else [
                {"cited": list(cited), "valid": all(1 <= n <= len(sources) for n in cited),
                 "supported": ok}]}


def test_cited_chunks_ignores_numbers_that_are_not_sources():
    assert cited_chunks(record("q", cited=(2, 9))) == {"c2"}


def test_summarise_counts_refusals_answers_and_grounding():
    relevant = {"a1": {"c1"}, "a2": {"c9"}, "a3": {"c1"}}
    records = [
        record("a1"),                                  # answered, cites the gold chunk
        record("a2"),                                  # answered, gold chunk not retrieved
        record("a3", refused_by="guardrail", sources=()),
        record("n1", refused_by="guardrail", sources=()),
        record("n2", refused_by="model"),
        record("n3", ok=False),                        # a negative that got answered
    ]

    counts = summarise(records, relevant)

    assert (counts["answerable"], counts["negative"]) == (3, 3)
    assert counts["answerable answered"] == 2 and counts["answerable refused by guardrail"] == 1
    assert counts["negative refused by guardrail"] == 1 and counts["negative refused by model"] == 1
    assert counts["negative answered"] == 1
    assert counts["answers"] == 3 and counts["answers citation check ok"] == 2
    assert counts["answerable with the answer in its sources"] == 1
    assert counts["answerable grounded"] == 1


def test_to_record_flattens_an_answer_for_the_jsonl():
    pipeline, _ = answerer("Hypomagnesemia has been reported [1].")

    row = to_record("d078", pipeline.answer(QUESTION), MIN_SUPPORT)

    assert row["qid"] == "d078" and row["sources"] == ["c1", "c2"] and row["citations_ok"]
    assert row["sentences"][0]["cited"] == [1] and row["sentences"][0]["supported"]
    assert row["backend"] == "fake" and row["seconds"] >= 0


def test_span_recall_is_the_weighted_share_of_the_gold_span_in_the_answer():
    """Span words: maximum, daily, dose, 450, mg. The answer has all but 'daily'.
    Counted equally that is 4 of 5; with 450 weighted 6 and the rest 1, 9 of 10."""
    from rag.eval.answer_eval import span_recall

    answer = "The maximum dose should not exceed 450 mg [1]."
    span = "maximum daily dose of 450 mg"

    assert span_recall(answer, span) == 0.8
    assert span_recall(answer, span, weight=lambda word: 6.0 if word == "450" else 1.0) == 0.9
    assert span_recall("Nothing relevant.", span) == 0.0


def test_summarise_counts_answers_that_state_the_gold_answer():
    relevant = {"a1": {"c1"}, "a2": {"c9"}}

    counts = summarise([record("a1"), record("a2")], relevant, stated=["a2"])

    assert counts["answerable stating the gold answer"] == 1


def test_recheck_scores_a_saved_answer_again_without_a_model():
    """A saved answer whose citations were in the model's own style, U+3010 1
    U+2020 L1-L4 U+3011, was stored as uncited. Rechecked, it is cited, valid,
    supported, and rewritten with [1]."""
    from rag.eval.answer_eval import recheck

    saved = {"qid": "d078", "question": QUESTION, "refused_by": None, "sources": ["c1", "c2"],
             "answer": "Hypomagnesemia has been reported\u30101\u2020L1-L4\u3011.",
             "citations_ok": False, "sentences": [{"cited": [], "valid": True, "supported": False}]}

    row = recheck(saved, TEXTS, MIN_SUPPORT)

    assert row["answer"] == "Hypomagnesemia has been reported[1]."
    assert row["citations_ok"] and row["sentences"][0]["cited"] == [1]
    assert row["qid"] == "d078" and row["refused_by"] is None


def test_recheck_leaves_a_guardrail_refusal_alone_and_spots_a_model_refusal():
    from rag.eval.answer_eval import recheck

    guarded = {"qid": "n1", "question": "q", "refused_by": "guardrail", "sources": [], "answer": "No label..."}
    refused = {"qid": "a1", "question": QUESTION, "refused_by": None, "sources": ["c1"],
               "answer": REFUSAL, "citations_ok": False, "sentences": []}

    assert recheck(guarded, TEXTS, MIN_SUPPORT) == guarded
    assert recheck(refused, TEXTS, MIN_SUPPORT)["refused_by"] == "model"


def test_a_model_refusal_is_a_mistake_only_with_the_answer_in_its_sources():
    relevant = {"a1": {"c1"}, "a2": {"c9"}}
    records = [record("a1", refused_by="model"),      # the gold chunk c1 was in its sources
               record("a2", refused_by="model")]      # c9 was not retrieved: refusing is right

    counts = summarise(records, relevant)

    assert counts["answerable refused by model"] == 2
    assert counts["model refusals with the answer in its sources"] == 1


def test_source_parts_splits_names_section_and_text():
    from rag.generate.answer import source_parts
    from rag.generate.prompt import Source

    source = Source("c1", "PANTOPRAZOLE (brand PROTONIX)\nWarnings And Cautions\nLine one.\nLine two.")

    assert source_parts(source) == ("PANTOPRAZOLE (brand PROTONIX)", "Warnings And Cautions", "Line one.\nLine two.")


def test_problems_names_what_is_wrong_with_each_flagged_sentence():
    from rag.generate.answer import problems
    from rag.generate.prompt import Source, check_citations

    sources = [Source("c1", TEXTS["c1"])]
    report = check_citations("Hypomagnesemia has been reported [1]. Kidney failure is common. "
                             "Alopecia occurs [4]. Seizures and rash follow [1].", sources, QUESTION)

    found = problems(report)

    assert [reason for _, reason in found] == [
        "no source is cited", "it cites a source number that does not exist",
        "its words are mostly not in the sources it cites"]
    assert problems(None) == [] and problems(check_citations("Hypomagnesemia has been reported [1].", sources)) == []
