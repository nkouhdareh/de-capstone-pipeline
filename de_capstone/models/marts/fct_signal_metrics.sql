{{ config(materialized='table') }}

with fct as (
    select f.safety_report_id, f.drug_key, f.reaction_key, d.year, d.month
    from {{ ref('fct_report_drug_reaction') }} f
    join {{ ref('dim_date') }} d on f.receive_date_key = d.date_key
    where f.drug_characterisation = 'SUSPECT' and f.drug_key <> -1
),
cases     as ( select distinct safety_report_id, drug_key, reaction_key, year, month from fct ),
periods   as ( select year, month, count(distinct safety_report_id) as n            from cases group by year, month ),
drug_tot  as ( select year, month, drug_key,     count(distinct safety_report_id) as n_drug  from cases group by year, month, drug_key ),
react_tot as ( select year, month, reaction_key, count(distinct safety_report_id) as n_react from cases group by year, month, reaction_key ),
pair_a    as ( select year, month, drug_key, reaction_key, count(distinct safety_report_id) as a from cases group by year, month, drug_key, reaction_key ),
abcd as (
    select p.year, p.month, p.drug_key, p.reaction_key,
        (p.a)::float                                 as a,
        (dt.n_drug  - p.a)::float                    as b,
        (rt.n_react - p.a)::float                    as c,
        (pr.n - dt.n_drug - rt.n_react + p.a)::float as d
    from pair_a p
    join drug_tot  dt on p.year=dt.year and p.month=dt.month and p.drug_key=dt.drug_key
    join react_tot rt on p.year=rt.year and p.month=rt.month and p.reaction_key=rt.reaction_key
    join periods   pr on p.year=pr.year and p.month=pr.month
),
metrics as (
    select year, month, drug_key, reaction_key, a, b, c, d,
        {{ metric_prr('a','b','c','d') }}          as prr,
        {{ metric_ror('a','b','c','d') }}          as ror,
        {{ metric_ror_ci_lower('a','b','c','d') }} as ror_ci_lower,
        {{ metric_chi2_yates('a','b','c','d') }}   as chi2_yates
    from abcd
)
select
    (m.year * 100 + m.month) as period_key,   -- YYYYMM
    m.year, m.month,
    m.drug_key, dd.drug_name, m.reaction_key, rx.reaction_pt,
    cast(m.a as integer) as a, cast(m.b as integer) as b,
    cast(m.c as integer) as c, cast(m.d as integer) as d,
    m.prr, m.ror, m.ror_ci_lower, m.chi2_yates,
    coalesce(m.a >= {{ var('signal_min_cases') }}
        and m.prr >= {{ var('signal_min_prr') }}
        and m.chi2_yates >= {{ var('signal_min_chi2') }}, false) as is_signal,
    coalesce(m.a >= {{ var('signal_min_cases') }}
        and m.prr >= {{ var('signal_min_prr') }}
        and m.chi2_yates >= {{ var('signal_min_chi2') }}
        and m.ror_ci_lower > {{ var('signal_ror_ci_min') }}, false) as is_signal_strict,    
    '{{ invocation_id }}' as _run_id,
    {{ dbt.current_timestamp() }} as _loaded_at
from metrics m
left join {{ ref('dim_drug') }}     dd on m.drug_key = dd.drug_key
left join {{ ref('dim_reaction') }} rx on m.reaction_key = rx.reaction_key
