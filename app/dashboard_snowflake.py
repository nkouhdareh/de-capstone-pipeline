"""Streamlit in Snowflake - openFDA drug-safety signal screening.

The Snowflake-hosted twin of app/dashboard_enhanced.py. Identical charts, tabs,
filters and SQL; only the connection differs.

Four differences from the local version:
  1. no `from db import connect` - Snowflake supplies an authenticated session
  2. get_active_session() instead of key-pair auth (no credentials in this file)
  3. session.sql(...).to_pandas() instead of a cursor
  4. `?` instead of `?` for bind parameters (Snowpark uses qmark binding)

Runs as DE_CAPSTONE_DBT_ROLE on DE_CAPSTONE_WH - a reader, not an administrator.
Deployed via Snowsight: Projects -> Streamlit -> Create on warehouse (legacy).
Packages required: plotly (declared in the app's environment.yml).
"""

import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from snowflake.snowpark.context import get_active_session


ANY = "(any)"
ALL_TIME = "All time"

# Snowsight decides the page background. "plotly_white" suits Snowsight's
# light theme; switch to "plotly_dark" if you set Snowsight to dark mode.
PLOTLY_TEMPLATE = "plotly_white"

COLOUR_STRICT = "#ef553b"
COLOUR_SIGNAL = "#f2b134"
COLOUR_PLAIN = "#4c78a8"

STATUS_COLOURS = {
    "Strict signal": COLOUR_STRICT,
    "Signal": COLOUR_SIGNAL,
    "Not flagged": COLOUR_PLAIN,
}

RANK_COLUMNS = {
    "PRR": "prr",
    "ROR": "ror",
    "Cases (a)": "a",
    "Chi-square": "chi2_yates",
}

NUMERIC_COLUMNS = (
    "a",
    "b",
    "c",
    "d",
    "prr",
    "ror",
    "ror_ci_lower",
    "chi2_yates",
)

VOLCANO_LIMIT = 5000

# Figures from the Silver build. These live in Parquet on D:, not in Snowflake,
# so they are shown as documented values and never presented as live queries.
SILVER_ATOMIC_ROWS = 93_366_638
SILVER_CLEAN_ROWS = 45_030_932
SILVER_QUARANTINED = 431_760
SILVER_DEDUP_SHARE = 51.8

DBT_RUN_NOTE = (
    "dbt build PASS=53 / dbt test PASS=42 from the last orchestrated run"
)


st.set_page_config(
    page_title="Drug-safety signal screening",
    page_icon="💊",
    layout="wide",
)


# ---------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------

@st.cache_resource
def get_session():
    """The session Snowflake hands the app - no credentials in this file."""
    return get_active_session()


@st.cache_data(ttl=3600)
def run_query(sql, params=()):
    """Run a read-only SELECT and return a DataFrame."""
    session = get_session()

    if params:
        frame = session.sql(sql, params=list(params)).to_pandas()
    else:
        frame = session.sql(sql).to_pandas()

    frame.columns = [column.lower() for column in frame.columns]

    for column in NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return frame


# ---------------------------------------------------------------------
# Lookups (dimension tables - fast)
# ---------------------------------------------------------------------

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


def load_periods():
    return run_query(
        "select distinct period_key, year, month "
        "from fct_signal_metrics order by period_key"
    )


# ---------------------------------------------------------------------
# Headline metrics and build metadata
# ---------------------------------------------------------------------

def load_headline_metrics():
    """Pairs, flagged and strictly flagged - one pass over the view."""
    return run_query(
        "select count(*) as pairs,"
        " sum(case when is_signal then 1 else 0 end) as signals,"
        " sum(case when is_signal_strict then 1 else 0 end) as strict_signals"
        " from sem_signal_metrics"
    )


def load_fact_rows():
    return run_query(
        "select count(*) as fact_rows from fct_report_drug_reaction"
    )


def load_build_stamp():
    """When dbt last rebuilt the models, and under which invocation id."""
    return run_query(
        "select max(_loaded_at) as built_at, max(_run_id) as run_id "
        "from fct_signal_metrics"
    )


def load_dim_counts():
    return run_query(
        "select"
        " (select count(*) from dim_drug)     as drugs,"
        " (select count(*) from dim_reaction) as reactions,"
        " (select count(*) from dim_reporter) as reporters,"
        " (select count(*) from dim_date)     as dates"
    )


def load_resolution_rates():
    return run_query(
        "select"
        " (select count(*) from fct_report_drug_reaction where drug_key = -1)"
        "     as unresolved_rows,"
        " (select count(*) from int_drug_resolution) as signatures,"
        " (select count(*) from int_drug_resolution where is_resolved)"
        "     as resolved_signatures"
    )


# ---------------------------------------------------------------------
# Analytical queries
# ---------------------------------------------------------------------

def build_signal_query(drug, reaction, min_cases, strict_only, rank_by, limit):
    """All-time ranking, from the sem_signal_metrics view."""
    conditions = ["a >= ?"]
    params = [int(min_cases)]

    if drug != ANY:
        conditions.append("drug_name = ?")
        params.append(drug)

    if reaction != ANY:
        conditions.append("reaction_pt = ?")
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


def build_period_query(period_key, drug, reaction, min_cases,
                       strict_only, rank_by, limit):
    """One month, from the materialised fct_signal_metrics table."""
    conditions = ["period_key = ?", "a >= ?"]
    params = [int(period_key), int(min_cases)]

    if drug != ANY:
        conditions.append("drug_name = ?")
        params.append(drug)

    if reaction != ANY:
        conditions.append("reaction_pt = ?")
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


def load_volcano(min_cases):
    """Top pairs by chi-square - the plot is capped and says so."""
    return run_query(
        "select drug_name, reaction_pt, a, prr, chi2_yates,"
        " is_signal, is_signal_strict"
        " from sem_signal_metrics"
        " where a >= ? and prr is not null and chi2_yates is not null"
        f" order by chi2_yates desc limit {VOLCANO_LIMIT}",
        (int(min_cases),),
    )


def load_heatmap_source(min_cases):
    """Flagged pairs above a case floor; the top-20 x top-20 grid is
    selected in pandas so the view is only scanned once."""
    return run_query(
        "select drug_name, reaction_pt, a, prr"
        " from sem_signal_metrics"
        " where is_signal and prr is not null and a >= ?",
        (int(min_cases),),
    )


def load_drug_profile(drug, min_cases, limit=20):
    return run_query(
        "select drug_name, reaction_pt, a, prr, ror, ror_ci_lower,"
        " chi2_yates, is_signal, is_signal_strict"
        " from sem_signal_metrics"
        " where drug_name = ? and a >= ?"
        f" order by prr desc nulls last limit {int(limit)}",
        (drug, int(min_cases)),
    )


def load_pair_trend(drug, reaction):
    return run_query(
        "select year, month, a, prr, chi2_yates from fct_signal_metrics "
        "where drug_name = ? and reaction_pt = ? order by period_key",
        (drug, reaction),
    )


# ---------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------

def signal_status(frame):
    return [
        "Strict signal" if strict else ("Signal" if signal else "Not flagged")
        for signal, strict in zip(frame["is_signal"], frame["is_signal_strict"])
    ]


def pair_label(frame):
    return frame["drug_name"] + " → " + frame["reaction_pt"]


def safe_log10(value):
    if value is None or pd.isna(value) or value <= 0:
        return None
    return math.log10(value)


def style(figure, height=420):
    figure.update_layout(
        template=PLOTLY_TEMPLATE,
        height=height,
        margin=dict(l=10, r=10, t=100, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=dict(x=0, xanchor="left", y=0.97, yanchor="top"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.08,
            x=0,
            title=None,
        ),
    )
    return figure


def bar_top_signals(frame, rank_by, top_n=20):
    data = frame.head(top_n).copy()
    data["pair"] = pair_label(data)
    data["status"] = signal_status(data)

    figure = px.bar(
        data.iloc[::-1],
        x=RANK_COLUMNS[rank_by],
        y="pair",
        orientation="h",
        color="status",
        color_discrete_map=STATUS_COLOURS,
        hover_data=["a", "prr", "ror", "chi2_yates"],
        title=f"Top {len(data)} candidate signals by {rank_by}",
    )

    figure.update_layout(xaxis_title=rank_by, yaxis_title=None)
    figure.update_yaxes(
        categoryorder="array",
        categoryarray=list(data.iloc[::-1]["pair"]),
    )    

    return style(figure, height=max(400, 26 * len(data)))


def volcano_figure(frame):
    data = frame.copy()
    data = data[(data["prr"] > 0) & (data["chi2_yates"] > 0)]

    if data.empty:
        return None

    data["status"] = signal_status(data)
    data["pair"] = pair_label(data)

    figure = px.scatter(
        data,
        x="prr",
        y="chi2_yates",
        size="a",
        color="status",
        color_discrete_map=STATUS_COLOURS,
        hover_name="pair",
        hover_data={
            "a": True,
            "prr": ":.2f",
            "chi2_yates": ":.0f",
            "status": False,
        },
        log_x=True,
        log_y=True,
        size_max=32,
        opacity=0.6,
         render_mode="svg",
        title="Volcano plot - disproportionality against statistical support",
    )

    figure.update_layout(
        xaxis_title="PRR (log scale)",
        yaxis_title="Chi-square, Yates corrected (log scale)",
    )

    return style(figure, height=540)


def funnel_figure(pairs, signals, strict_signals):
    figure = go.Figure(
        go.Funnel(
            y=[
                "Atomic rows (pre-dedup)",
                "Clean Silver rows",
                "Scored drug x reaction pairs",
                "Candidate signals",
                "Strict signals",
            ],
            x=[
                SILVER_ATOMIC_ROWS,
                SILVER_CLEAN_ROWS,
                pairs,
                signals,
                strict_signals,
            ],
            textinfo="value+percent initial",
            marker=dict(color=COLOUR_PLAIN),
        )
    )

    figure.update_layout(title="Pipeline funnel - rows to candidates")

    return style(figure, height=440)


def status_donut(pairs, signals, strict_signals):
    figure = go.Figure(
        go.Pie(
            labels=["Not flagged", "Signal", "Strict signal"],
            values=[pairs - signals, signals - strict_signals, strict_signals],
            hole=0.58,
            sort=False,
            marker=dict(colors=[COLOUR_PLAIN, COLOUR_SIGNAL, COLOUR_STRICT]),
        )
    )

    figure.update_layout(title="Share of scored pairs by flag")

    return style(figure, height=440)


def trend_figure(frame, drug, reaction):
    data = frame.copy()
    data["period"] = [
        f"{int(year)}-{int(month):02d}"
        for year, month in zip(data["year"], data["month"])
    ]

    figure = make_subplots(specs=[[{"secondary_y": True}]])

    figure.add_trace(
        go.Bar(
            x=data["period"],
            y=data["a"],
            name="Cases (a)",
            marker_color=COLOUR_PLAIN,
            opacity=0.8,
        ),
        secondary_y=False,
    )

    figure.add_trace(
        go.Scatter(
            x=data["period"],
            y=data["prr"],
            name="PRR",
            mode="lines+markers",
            line=dict(color=COLOUR_STRICT, width=3),
        ),
        secondary_y=True,
    )

    figure.update_yaxes(title_text="Cases (a)", secondary_y=False)
    figure.update_yaxes(title_text="PRR", secondary_y=True, showgrid=False)

    figure.update_layout(
        title=f"{drug} → {reaction}: monthly PRR and case count"
    )

    return style(figure, height=440)


def heatmap_figure(frame, top_drugs=20, top_reactions=20):
    drugs = frame["drug_name"].value_counts().head(top_drugs).index
    reactions = frame["reaction_pt"].value_counts().head(top_reactions).index

    subset = frame[
        frame["drug_name"].isin(drugs)
        & frame["reaction_pt"].isin(reactions)
    ]

    if subset.empty:
        return None

    pivot = subset.pivot_table(
        index="drug_name",
        columns="reaction_pt",
        values="prr",
        aggfunc="max",
    )

    logged = pivot.apply(lambda column: column.map(safe_log10))

    figure = px.imshow(
        logged,
        color_continuous_scale="Reds",
        aspect="auto",
        labels=dict(color="log10 PRR"),
        title=(
            f"PRR heatmap - {len(pivot.index)} most-flagged drugs "
            f"x {len(pivot.columns)} most-flagged reactions"
        ),
    )

    figure.update_xaxes(tickangle=45, title=None)
    figure.update_yaxes(title=None)

    return style(figure, height=640)


TABLE_COLUMNS = {
    "drug_name": st.column_config.TextColumn("Drug"),
    "reaction_pt": st.column_config.TextColumn("Reaction"),
    "a": st.column_config.NumberColumn("Cases (a)", format="%d"),
    "prr": st.column_config.NumberColumn("PRR", format="%.2f"),
    "ror": st.column_config.NumberColumn("ROR", format="%.2f"),
    "ror_ci_lower": st.column_config.NumberColumn("ROR CI lower", format="%.2f"),
    "chi2_yates": st.column_config.NumberColumn("Chi-square", format="%.0f"),
    "is_signal": st.column_config.CheckboxColumn("Signal"),
    "is_signal_strict": st.column_config.CheckboxColumn("Strict"),
}


# ---------------------------------------------------------------------
# Header and KPI row
# ---------------------------------------------------------------------

st.title("💊 Drug-safety signal screening")

st.markdown(
    "Pharmacovigilance signal detection over **openFDA FAERS 2023-2024**. "
    "Adverse-event reports are flattened to one row per case x drug x reaction, "
    "loaded to Snowflake and modelled into a star schema, where each drug x "
    "reaction pair gets a 2x2 disproportionality table and its PRR, ROR, "
    "ROR confidence interval and Yates-corrected chi-square. "
    "**Disproportionality is a screening tool, not causal evidence** - this "
    "page is a ranked candidate list with its support shown, for an expert to "
    "triage."
)

headline = load_headline_metrics()
fact_rows = load_fact_rows()
build_stamp = load_build_stamp()

pairs = int(headline["pairs"].iloc[0])
signals = int(headline["signals"].iloc[0])
strict_signals = int(headline["strict_signals"].iloc[0])
silver_rows = int(fact_rows["fact_rows"].iloc[0])

built_at = build_stamp["built_at"].iloc[0]
run_id = build_stamp["run_id"].iloc[0]

if built_at is None or pd.isna(built_at):
    built_at_text = "unknown"
else:
    built_at_text = pd.Timestamp(built_at).strftime("%Y-%m-%d %H:%M")

kpi_1, kpi_2, kpi_3, kpi_4 = st.columns(4)

kpi_1.metric(
    "Silver rows",
    f"{silver_rows:,}",
    help="Rows in fct_report_drug_reaction - one per case x resolved drug x "
         "characterisation x reaction, 1:1 with the Silver layer.",
)

kpi_2.metric(
    "Scored pairs",
    f"{pairs:,}",
    help="Distinct drug x reaction pairs with a 2x2 table, restricted to "
         "SUSPECT drugs with a resolved identity (drug_key <> -1).",
)

kpi_3.metric(
    "Candidate signals",
    f"{signals:,}",
    delta=f"{signals / pairs:.1%} of pairs",
    delta_color="off",
    help="is_signal: a >= 3 and PRR >= 2.0 and chi-square >= 4.0. "
         f"is_signal_strict adds ROR CI lower > 1.0 and prunes only "
         f"{signals - strict_signals:,} of them.",
)

kpi_4.metric(
    "Models last built",
    built_at_text,
    help=f"Live _loaded_at from fct_signal_metrics. dbt invocation {run_id}. "
         f"{DBT_RUN_NOTE} - documented metadata, not checked by this app.",
)


# ---------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------

with st.sidebar:
    st.header("Filters")

    drug = st.selectbox("Drug", load_drug_names())
    reaction = st.selectbox("Reaction", load_reaction_terms())

    periods = load_periods()

    period_labels = [ALL_TIME] + [
        f"{int(row.year)}-{int(row.month):02d}"
        for row in periods.itertuples()
    ]

    period_choice = st.selectbox("Period", period_labels)

    min_cases = st.number_input(
        "Minimum cases (a) - all time",
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

    with st.expander("How to read these numbers"):
        st.markdown(
            "**The 2x2 table.** For one drug and one reaction: `a` cases "
            "report both, `b` report the drug without the reaction, `c` "
            "report the reaction without the drug, `d` report neither.\n\n"
            "**PRR** (proportional reporting ratio) = the share of the "
            "drug's reports mentioning this reaction, divided by the same "
            "share among all other drugs. PRR 35 means the reaction is "
            "reported about 35 times more often for this drug than "
            "background.\n\n"
            "**ROR** (reporting odds ratio) = `(a*d)/(b*c)`. It answers the "
            "same question with odds instead of proportions and behaves "
            "better when the reaction is rare.\n\n"
            "**ROR CI lower** = the lower bound of the 95% confidence "
            "interval. If it sits above 1, the association is unlikely to "
            "be chance alone. This is what `is_signal_strict` adds.\n\n"
            "**Chi-square (Yates)** = statistical support. It grows with the "
            "number of reports, so a large chi-square means *well "
            "evidenced*, not *large effect*.\n\n"
            "**A blank PRR or ROR** means `c = 0`: the reaction was reported "
            "only with this drug, so the ratio is undefined rather than "
            "infinite. Those rows sort last.\n\n"
            "**Why candidates, not proof.** Disproportionality measures how "
            "often things are *reported together*, from a voluntary, "
            "unverified reporting system with no denominator of treated "
            "patients. High ratios routinely come from confounding by "
            "indication (a drug co-occurs with the condition it treats), "
            "device and product-use reports, notoriety and litigation-driven "
            "reporting, and duplicate submissions. It is a screening step "
            "that produces a ranked list for a clinical reviewer - never a "
            "causal claim."
        )

if period_choice == ALL_TIME:
    period_key = None
else:
    period_key = int(
        periods["period_key"].iloc[period_labels.index(period_choice) - 1]
    )


# ---------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------

tab_overview, tab_explorer, tab_profile, tab_quality = st.tabs([
    "Overview",
    "Signal Explorer",
    "Drug Profile",
    "Data Quality & Methodology",
])


with tab_overview:
    left, right = st.columns(2)

    with left:
        st.plotly_chart(
            funnel_figure(pairs, signals, strict_signals),
            width="stretch",
            key="overview_funnel",
        )
        st.caption(
            "The first two stages are documented figures from the Silver "
            "build (Parquet on D:, not in Snowflake); the last three are "
            "queried live."
        )

    with right:
        st.plotly_chart(
            status_donut(pairs, signals, strict_signals),
            width="stretch",
            key="overview_donut",
        )
        st.caption(
            f"`is_signal_strict` prunes only {signals - strict_signals:,} of "
            f"{signals:,} flagged pairs - a stricter statistical threshold "
            "does not separate real signals from artifacts. That is the "
            "argument for triage rather than a binary flag."
        )

    st.subheader("Where the signals sit")

    volcano_frame = load_volcano(min_cases)

    if volcano_frame.empty:
        st.info(
            "No pairs at this case floor. Lower 'Minimum cases (a) - all "
            "time' in the sidebar."
        )
    else:
        figure = volcano_figure(volcano_frame)

        if figure is None:
            st.info("No pairs with a defined PRR at this case floor.")
        else:
            st.plotly_chart(figure, width="stretch", key="overview_volcano")
            st.caption(
                f"Up to {VOLCANO_LIMIT:,} pairs ranked by chi-square, with at "
                f"least {int(min_cases):,} cases each "
                f"({len(volcano_frame):,} shown). Bubble size is the case "
                "count. Read it as: right = large effect, up = well "
                "evidenced. The point of the chart is that genuine "
                "label-level signals and known artifacts occupy the *same* "
                "top-right region - no threshold on this plane separates "
                "them, which is why the output is a candidate list."
            )


with tab_explorer:
    if period_key is None:
        explorer_sql, explorer_params = build_signal_query(
            drug, reaction, min_cases, strict_only, rank_by, limit
        )
        source_note = (
            f"sem_signal_metrics (all time), minimum {int(min_cases):,} cases"
        )
    else:
        explorer_sql, explorer_params = build_period_query(
            period_key, drug, reaction, min_cases_period,
            strict_only, rank_by, limit,
        )
        source_note = (
            f"fct_signal_metrics ({period_choice}), minimum "
            f"{int(min_cases_period):,} cases"
        )

    explorer_frame = run_query(explorer_sql, explorer_params)

    st.caption(f"Source: {source_note}")

    if explorer_frame.empty:
        st.info(
            "No pairs match these filters. The monthly grain needs a much "
            "lower case floor than all-time."
        )
    else:
        st.plotly_chart(
            bar_top_signals(explorer_frame, rank_by),
            width="stretch",
            key="explorer_bars",
        )

        st.subheader(
            f"Ranked candidates ({len(explorer_frame)} rows by {rank_by})"
        )

        st.dataframe(
            explorer_frame,
            hide_index=True,
            width="stretch",
            column_config=TABLE_COLUMNS,
            key="explorer_table",
        )

        st.caption(
            "Showing the top rows only - not the full matching set. "
            "Thresholds (a >= 3, PRR >= 2.0, chi-square >= 4.0, "
            "ROR CI > 1.0) are set in dbt_project.yml, not here."
        )


with tab_profile:
    if drug == ANY:
        st.info("Pick a drug in the sidebar to see its profile.")
    else:
        profile_frame = load_drug_profile(drug, min_cases)

        if profile_frame.empty:
            st.info(
                f"No reactions for {drug} with at least {int(min_cases):,} "
                "cases. Lower the all-time case floor in the sidebar."
            )
        else:
            st.subheader(f"{drug} - strongest reported associations")

            st.plotly_chart(
                bar_top_signals(profile_frame, "PRR"),
                width="stretch",
                key="profile_bars",
            )

            st.dataframe(
                profile_frame,
                hide_index=True,
                width="stretch",
                column_config=TABLE_COLUMNS,
                key="profile_table",
            )

        if reaction != ANY:
            trend_reaction = reaction
            trend_note = "Reaction chosen in the sidebar."
        elif not profile_frame.empty:
            trend_reaction = profile_frame["reaction_pt"].iloc[0]
            trend_note = (
                "No reaction selected, so this is the drug's top reaction "
                "by PRR. Pick one in the sidebar to change it."
            )
        else:
            trend_reaction = None
            trend_note = None

        if trend_reaction is not None:
            trend = load_pair_trend(drug, trend_reaction)

            st.subheader("Over time")
            st.caption(trend_note)

            if trend.empty:
                st.info("No monthly rows for this pair.")
            else:
                st.plotly_chart(
                    trend_figure(trend, drug, trend_reaction),
                    width="stretch",
                    key="profile_trend",
                )

                months_column, cases_column = st.columns(2)

                months_column.metric("Months present", len(trend))
                cases_column.metric(
                    "Cases across months",
                    f"{int(trend['a'].sum()):,}",
                    help="A case has exactly one receive_date, so it falls in "
                         "exactly one month - the monthly counts must sum "
                         "back to the all-time case count for this pair.",
                )

                st.caption(
                    "The 2x2 table is rebuilt *inside* each month, so a "
                    "monthly PRR is not a slice of the all-time PRR: it "
                    "answers 'strongest disproportionality this period'."
                )


with tab_quality:
    st.subheader("The models, as built")

    dim_counts = load_dim_counts()
    resolution = load_resolution_rates()

    unresolved_rows = int(resolution["unresolved_rows"].iloc[0])
    signatures = int(resolution["signatures"].iloc[0])
    resolved_signatures = int(resolution["resolved_signatures"].iloc[0])

    row_resolution = 1 - (unresolved_rows / silver_rows)
    signature_resolution = resolved_signatures / signatures

    quality_1, quality_2, quality_3, quality_4 = st.columns(4)

    quality_1.metric("Drugs (dim_drug)", f"{int(dim_counts['drugs'].iloc[0]):,}")
    quality_2.metric(
        "Reactions (dim_reaction)",
        f"{int(dim_counts['reactions'].iloc[0]):,}",
    )
    quality_3.metric(
        "Reporters (dim_reporter)",
        f"{int(dim_counts['reporters'].iloc[0]):,}",
    )
    quality_4.metric("Dates (dim_date)", f"{int(dim_counts['dates'].iloc[0]):,}")

    resolution_1, resolution_2 = st.columns(2)

    resolution_1.metric(
        "Drug resolution, by row",
        f"{row_resolution:.1%}",
        help=f"{silver_rows - unresolved_rows:,} of {silver_rows:,} fact rows "
             "carry a resolved drug identity (drug_key <> -1).",
    )

    resolution_2.metric(
        "Drug resolution, by distinct signature",
        f"{signature_resolution:.1%}",
        help=f"{resolved_signatures:,} of {signatures:,} distinct "
             "(name, rxcui, brand) signatures matched the NDC directory. The "
             "long tail of rare raw names stays unresolved - deliberately, "
             "since ambiguous matches are never guessed.",
    )

    st.caption(
        "All six figures above are queried live from Snowflake. The gap "
        "between them is the interesting part: a small share of distinct "
        "names covers the large majority of rows."
    )

    st.divider()

    st.subheader("Which drugs and reactions carry the flags")

    heatmap_frame = load_heatmap_source(min_cases)

    if heatmap_frame.empty:
        st.info("No flagged pairs at this case floor.")
    else:
        figure = heatmap_figure(heatmap_frame)

        if figure is None:
            st.info("Not enough overlap to build a grid at this case floor.")
        else:
            st.plotly_chart(figure, width="stretch", key="quality_heatmap")
            st.caption(
                f"Built from {len(heatmap_frame):,} flagged pairs with at "
                f"least {int(min_cases):,} cases. Colour is log10(PRR) "
                "because the values span several orders of magnitude; blank "
                "cells are pairs that were never flagged."
            )

    st.divider()

    st.subheader("Method and thresholds")

    threshold_frame = pd.DataFrame(
        {
            "Variable": [
                "signal_min_cases",
                "signal_min_prr",
                "signal_min_chi2",
                "signal_ror_ci_min",
            ],
            "Value": ["3", "2.0", "4.0", "1.0"],
            "Used by": [
                "is_signal, is_signal_strict",
                "is_signal, is_signal_strict",
                "is_signal, is_signal_strict",
                "is_signal_strict only",
            ],
        }
    )

    st.dataframe(
        threshold_frame,
        hide_index=True,
        width="stretch",
        key="quality_thresholds",
    )

    st.markdown(
        "Thresholds live in `dbt_project.yml` and the formulas in "
        "`macros/signal_metrics.sql`. **This dashboard computes nothing** - "
        "it filters, ranks and draws what the warehouse already calculated, "
        "so there is exactly one definition of every metric in the project. "
        "The formulas are covered by a dbt test against a hand-computed "
        "worked example (`tests/assert_signal_worked_example.sql`)."
    )

    st.markdown(
        "**Scope of the scored population.** Only drugs recorded as "
        "`SUSPECT` with a resolved identity (`drug_key <> -1`) enter the "
        "signal models. Concomitant medications are excluded, because a "
        "drug present alongside the suspect one would otherwise inherit its "
        "associations."
    )

    st.divider()

    st.subheader("From the Silver build (documented, not queried here)")

    st.markdown(
        f"These come from the PySpark Silver job and live as Parquet on the "
        f"D: drive, so this app cannot verify them at runtime:\n\n"
        f"- **{SILVER_ATOMIC_ROWS:,}** atomic rows before dedup, "
        f"**{SILVER_CLEAN_ROWS:,}** after - **{SILVER_DEDUP_SHARE}%** "
        "removed, the duplicates being repeated dosage lines for the same "
        "case, drug and reaction.\n"
        f"- **{SILVER_QUARANTINED:,}** rows quarantined with a reason and "
        "never silently dropped: 431,741 with a null reaction (all from three "
        "mega-reports whose reactions are entirely blank), 18 with an "
        "out-of-range `drugcharacterization`, 1 null.\n"
        f"- **0** null reactions and **0** duplicate grain keys in Silver.\n"
        f"- {DBT_RUN_NOTE}."
    )


# ---------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------

st.divider()

st.caption(
    "**Bronze** (openFDA API) → **Silver** (PySpark, 45,030,932 clean "
    "rows) → **S3** → **Snowflake RAW** → **dbt** (10 models, "
    "star schema, PRR/ROR signals) → **Airflow** (one trigger, 8 tasks)"
)

st.caption(
    f"Models last built {built_at_text} · dbt invocation `{run_id}` "
    f"· {DBT_RUN_NOTE} (documented metadata, not verified by this app) "
    "· this page issues read-only SELECT queries and computes no metrics"
)
