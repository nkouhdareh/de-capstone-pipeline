"""Streamlit dashboard - openFDA drug-safety signal screening.

Reads the dbt marts in DE_CAPSTONE.DBT_DEV. Nothing is computed here:
PRR / ROR / ROR-CI / chi2 come from sem_signal_metrics, which computes them
via macros/signal_metrics.sql. The dashboard only filters and ranks.

Run:  .venv-app/Scripts/streamlit.exe run app/dashboard.py --server.port 8501
"""

import pandas as pd
import streamlit as st

from db import connect

ANY = "(any)"

RANK_COLUMNS = {
    "PRR": "prr",
    "ROR": "ror",
    "Cases (a)": "a",
    "Chi-square": "chi2_yates",
}


st.set_page_config(
    page_title="Drug-safety signals",
    layout="wide",
)


@st.cache_resource
def get_connection():
    return connect()


@st.cache_data(ttl=3600)
def run_query(sql, params=()):
    cursor = get_connection().cursor()

    try:
        cursor.execute(sql, params)
        columns = [column[0].lower() for column in cursor.description]
        return pd.DataFrame(cursor.fetchall(), columns=columns)
    finally:
        cursor.close()


def load_drug_names():
    frame = run_query(
        "select drug_name from dim_drug "
        "where not is_unknown order by drug_name"
    )
    return [ANY] + frame["drug_name"].tolist()


def load_reaction_terms():
    frame = run_query(
        "select reaction_pt from dim_reaction order by reaction_pt"
    )
    return [ANY] + frame["reaction_pt"].tolist()


def build_signal_query(drug, reaction, min_cases, strict_only, rank_by, limit):
    conditions = ["a >= %s"]
    params = [int(min_cases)]

    if drug != ANY:
        conditions.append("drug_name = %s")
        params.append(drug)

    if reaction != ANY:
        conditions.append("reaction_pt = %s")
        params.append(reaction)

    if strict_only:
        conditions.append("is_signal_strict")

    sql = (
        "select drug_name, reaction_pt, a, prr, ror, ror_ci_lower,"
        " chi2_yates, is_signal, is_signal_strict"
        " from sem_signal_metrics"
        " where " + " and ".join(conditions) +
        f" order by {RANK_COLUMNS[rank_by]} desc nulls last"
        f" limit {int(limit)}"
    )

    return sql, tuple(params)


st.title("Drug-safety signal screening")

st.caption(
    "openFDA FAERS 2023-2024 - 45,030,932 drug-reaction rows, "
    "1,240,645 drug x reaction pairs. Disproportionality (PRR / ROR) is a "
    "**screening** tool, not causal evidence: the largest ratios are often "
    "confounding by indication, device product-use reports, or "
    "litigation-driven reporting. Rank by magnitude, then read the support "
    "(cases and chi-square) next to it."
)

with st.sidebar:
    st.header("Filters")

    drug = st.selectbox("Drug", load_drug_names())
    reaction = st.selectbox("Reaction", load_reaction_terms())

    min_cases = st.number_input(
        "Minimum cases (a)",
        min_value=1,
        value=100,
        step=10,
        help="Pairs below this are statistically fragile.",
    )

    min_cases_period = st.number_input(
        "Minimum cases (a) - monthly",
        min_value=1,
        value=5,
        step=1,
        help="Monthly counts are far smaller than all-time; 100 would "
             "return almost nothing.",
    )

    strict_only = st.checkbox(
        "Strict signals only (ROR CI lower > 1)",
        value=False,
    )

    rank_by = st.selectbox("Rank by", list(RANK_COLUMNS))

    limit = st.slider("Rows to show", 25, 500, 100, 25)

sql, params = build_signal_query(
    drug,
    reaction,
    min_cases,
    strict_only,
    rank_by,
    limit,
)

frame = run_query(sql, params)

st.subheader(f"Top {len(frame)} candidate signals by {rank_by}")

st.dataframe(
    frame,
    hide_index=True,
    width="stretch",
    column_config={
        "drug_name": st.column_config.TextColumn("Drug"),
        "reaction_pt": st.column_config.TextColumn("Reaction"),
        "a": st.column_config.NumberColumn("Cases (a)", format="%d"),
        "prr": st.column_config.NumberColumn("PRR", format="%.2f"),
        "ror": st.column_config.NumberColumn("ROR", format="%.2f"),
        "ror_ci_lower": st.column_config.NumberColumn(
            "ROR CI lower", format="%.2f"
        ),
        "chi2_yates": st.column_config.NumberColumn(
            "Chi-square", format="%.0f"
        ),
        "is_signal": st.column_config.CheckboxColumn("Signal"),
        "is_signal_strict": st.column_config.CheckboxColumn("Strict"),
    },
)

st.caption(
    "Showing the top rows only - not the full matching set. "
    "A blank PRR / ROR means the reaction was reported *only* with this drug "
    "(c = 0), so the ratio is undefined rather than infinite - these are "
    "sorted last, not first. "
    "Thresholds (a >= 3, PRR >= 2.0, chi-square >= 4.0, ROR CI > 1.0) are "
    "set in dbt_project.yml, not here."
)

# ---------------------------------------------------------------------
# Period view - fct_signal_metrics (drug x reaction x month)
# ---------------------------------------------------------------------

def load_periods():
    return run_query(
        "select distinct period_key, year, month "
        "from fct_signal_metrics order by period_key"
    )


def build_period_query(period_key, drug, reaction, min_cases,
                       strict_only, rank_by, limit):
    conditions = ["period_key = %s", "a >= %s"]
    params = [int(period_key), int(min_cases)]

    if drug != ANY:
        conditions.append("drug_name = %s")
        params.append(drug)

    if reaction != ANY:
        conditions.append("reaction_pt = %s")
        params.append(reaction)

    if strict_only:
        conditions.append("is_signal_strict")

    sql = (
        "select drug_name, reaction_pt, a, prr, ror, ror_ci_lower,"
        " chi2_yates, is_signal, is_signal_strict"
        " from fct_signal_metrics"
        " where " + " and ".join(conditions) +
        f" order by {RANK_COLUMNS[rank_by]} desc nulls last"
        f" limit {int(limit)}"
    )

    return sql, tuple(params)


st.divider()

st.header("Over time")

st.caption(
    "Monthly grain, from fct_signal_metrics. The 2x2 table is rebuilt "
    "*inside* each month, so a monthly PRR is not a slice of the all-time "
    "PRR above - it answers 'strongest disproportionality this period'."
)

periods = load_periods()

period_labels = [
    f"{int(row.year)}-{int(row.month):02d}"
    for row in periods.itertuples()
]

period_choice = st.selectbox(
    "Month",
    period_labels,
    index=len(period_labels) - 1,
)

period_key = periods["period_key"].iloc[
    period_labels.index(period_choice)
]

period_sql, period_params = build_period_query(
    period_key,
    drug,
    reaction,
    min_cases_period,
    strict_only,
    rank_by,
    limit,
)

period_frame = run_query(period_sql, period_params)

st.subheader(f"{period_choice}: top {len(period_frame)} by {rank_by}")

st.dataframe(period_frame, hide_index=True, width="stretch")

# ---- monthly trend for one pair ----

if drug != ANY and reaction != ANY:
    trend = run_query(
        "select year, month, a, prr, chi2_yates from fct_signal_metrics "
        "where drug_name = %s and reaction_pt = %s order by period_key",
        (drug, reaction),
    )

    st.subheader(f"{drug} - {reaction}: monthly trend")

    if trend.empty:
        st.info("No monthly rows for this pair.")
    else:
        trend["period"] = [
            f"{int(year)}-{int(month):02d}"
            for year, month in zip(trend["year"], trend["month"])
        ]

        left, right = st.columns(2)

        with left:
            st.metric("Months present", len(trend))

        with right:
            st.metric("Cases across months", int(trend["a"].sum()))

        st.markdown("**PRR by month**")
        st.line_chart(trend, x="period", y="prr")

        st.markdown("**Cases (a) by month**")
        st.bar_chart(trend, x="period", y="a")
else:
    st.info(
        "Pick both a drug and a reaction in the sidebar "
        "to see that pair's monthly trend."
    )