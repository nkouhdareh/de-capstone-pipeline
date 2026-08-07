{{ config(materialized='view') }}

with fct as (
    select safety_report_id, drug_key, reaction_key
    from {{ ref('fct_report_drug_reaction') }}
    where drug_characterisation = 'SUSPECT' and drug_key <> -1
),
cases as ( select distinct safety_report_id, drug_key, reaction_key from fct ),
n_total as ( select count(distinct safety_report_id) as n from cases ),
drug_tot as ( select drug_key, count(distinct safety_report_id) as n_drug from cases group by drug_key ),
react_tot as ( select reaction_key, count(distinct safety_report_id) as n_react from cases group by reaction_key ),
pair_a as ( select drug_key, reaction_key, count(distinct safety_report_id) as a from cases group by drug_key, reaction_key ),
abcd as (
    select p.drug_key, p.reaction_key,
        (p.a)::float as a,
        (dt.n_drug - p.a)::float as b,
        (rt.n_react - p.a)::float as c,
        (n.n - dt.n_drug - rt.n_react + p.a)::float as d
    from pair_a p
    join drug_tot dt on p.drug_key = dt.drug_key
    join react_tot rt on p.reaction_key = rt.reaction_key
    cross join n_total n
),
metrics as (
    select drug_key, reaction_key, a, b, c, d,
        {{ metric_prr('a','b','c','d') }} as prr,
        {{ metric_ror('a','b','c','d') }} as ror,
        {{ metric_ror_ci_lower('a','b','c','d') }} as ror_ci_lower,
        {{ metric_chi2_yates('a','b','c','d') }} as chi2_yates
    from abcd
)
select
    m.drug_key, dd.drug_name, m.reaction_key, rx.reaction_pt,
    cast(m.a as integer) as a, cast(m.b as integer) as b,
    cast(m.c as integer) as c, cast(m.d as integer) as d,
    m.prr, m.ror, m.ror_ci_lower, m.chi2_yates,
    coalesce(m.a >= {{ var('signal_min_cases') }}
        and m.prr >= {{ var('signal_min_prr') }}
        and m.chi2_yates >= {{ var('signal_min_chi2') }}, false) as is_signal
from metrics m
left join {{ ref('dim_drug') }} dd on m.drug_key = dd.drug_key
left join {{ ref('dim_reaction') }} rx on m.reaction_key = rx.reaction_key
