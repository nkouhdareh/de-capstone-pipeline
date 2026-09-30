"""The "Ask the labels" tab: a question box over the drug-label retrieval system.

    question -> guardrail -> hybrid search, top 5 chunks -> a language model
             -> an answer with [1] [2] citations, each checked against its source

Everything it shows comes from rag/: this file is only the screen. It is kept
apart from dashboard_enhanced.py so the four existing tabs do not depend on the
retrieval packages: if those are missing, this tab says so and the rest of the
dashboard works as before.

It runs locally only. The indexes are files on this machine (data/rag/index/),
the question is embedded by a local model, and the answer is written either by
a hosted model on Groq (about a second; needs GROQ_API_KEY in .env) or by a
local one on Ollama (about a minute; needs nothing). Streamlit in Snowflake can
reach none of those, so dashboard_snowflake.py has no such tab.

The indexes load once per server process, about five seconds, and are shared by
every rerun.
"""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:           # so `import rag` works whatever folder streamlit starts in
    sys.path.insert(0, str(ROOT))

BACKENDS = {
    "Hosted: gpt-oss-120b on Groq (about a second)": "groq",
    "Local: llama3.2:3b on Ollama (about a minute)": "ollama",
}
EXAMPLES = [
    "Does the pantoprazole label report low magnesium levels?",
    "What is the maximum daily dose of captopril tablets?",
    "Is SEROQUEL XR approved for elderly patients with dementia-related psychosis?",
    "What is the maximum daily dose of gliclazide?",
]
DISCLAIMER = (
    "This tool quotes **US drug label text** from openFDA. It is **not medical advice**: "
    "a label can be out of date, and the answer can be wrong. Read the sources under every answer."
)


@st.cache_resource(show_spinner="Loading the label index, about five seconds, once...")
def load_search():
    """The retrieval half, built once: both indexes, the guardrail, the chunk texts."""
    from rag.generate.answer import idf_weight
    from rag.retrieve.dense import DenseRetriever
    from rag.retrieve.fusion import COLLAPSE_ABOVE, HybridRetriever
    from rag.retrieve.guardrail import Guardrail
    from rag.retrieve.rerank import ChunkTexts
    from rag.retrieve.sparse import SparseRetriever

    dense, sparse = DenseRetriever(), SparseRetriever()
    return {
        "retriever": HybridRetriever(dense, sparse, collapse_above=COLLAPSE_ABOVE),
        "guardrail": Guardrail(dense, sparse),
        "texts": ChunkTexts(),
        "stem": sparse.stem,
        "weight": idf_weight(sparse),
    }


def ask(question: str, backend_name: str):
    from rag.generate.answer import Answerer
    from rag.generate.backends import LazyBackend

    search = load_search()
    answerer = Answerer(search["retriever"], search["guardrail"], search["texts"],
                        LazyBackend(backend_name), stem=search["stem"], weight=search["weight"])
    return answerer.answer(question)


def show(answer) -> None:
    from rag.generate.answer import problems, source_parts

    if answer.refused_by == "guardrail":
        st.error(answer.text)
        if answer.verdict.unknown_words:
            st.caption("Refused before any model was called: that word is in no label in the index. "
                       "Check the spelling, or the drug may have no US label here.")
        else:
            st.caption("Refused before any model was called: nothing in the index is close enough to the "
                       f"question (best similarity {answer.verdict.best_cosine:.3f}).")
        return

    if answer.refused_by == "model":
        st.info(answer.text)
        st.caption("The model read the five closest label sections below and found no answer in them.")
    else:
        st.markdown(answer.text)
        flagged = problems(answer.report)
        if not flagged:
            st.success("Citation check passed: every sentence cites a source, and its words are in that source.")
        else:
            st.warning("Citation check: read these sentences against their sources before trusting them.")
            for sentence, reason in flagged:
                st.markdown(f"- {reason}: *{sentence}*")

    generation = answer.generation
    st.caption(f"{generation.backend} | {answer.seconds:.1f} s | "
               f"{generation.prompt_tokens:,} tokens read, {generation.answer_tokens:,} written")
    st.markdown("**Sources**, the label sections the model was given:")
    for number, source in enumerate(answer.sources, start=1):
        names, section, body = source_parts(source)
        with st.expander(f"[{number}] {names} | {section}"):
            st.write(body)
            st.caption(f"chunk {source.chunk_id}")


def render() -> None:
    st.subheader("Ask the drug labels")
    st.warning(DISCLAIMER)

    try:
        import rag.generate.answer  # noqa: F401
    except ImportError as error:
        st.info(f"This tab needs the retrieval packages, which this environment does not have: {error}. "
                "Install them with: python -m pip install fastembed==0.8.1")
        return

    st.caption("Try one:")
    for column, example in zip(st.columns(len(EXAMPLES)), EXAMPLES):
        if column.button(example, key=f"rag_example_{example}"):
            st.session_state["rag_question"] = example

    with st.form("rag_form"):
        question = st.text_input("Your question about a drug label", key="rag_question",
                                 placeholder="Is teeth grinding listed as a side effect of duloxetine?")
        backend_label = st.radio("Answer written by", list(BACKENDS), key="rag_backend", horizontal=True)
        asked = st.form_submit_button("Ask")

    if not asked:
        return
    if not question.strip():
        st.info("Type a question first.")
        return
    try:
        with st.spinner("Searching the labels and writing the answer..."):
            answer = ask(question.strip(), BACKENDS[backend_label])
    except Exception as error:      # noqa: BLE001  a missing key or a stopped Ollama must not break the page
        st.error(f"The answer could not be written: {error}")
        if "GROQ_API_KEY" in str(error):
            st.caption("Add GROQ_API_KEY to .env, or choose the local model.")
        elif BACKENDS[backend_label] == "ollama":
            st.caption("Is the Ollama app running? Start it, or choose the hosted model.")
        return
    show(answer)
