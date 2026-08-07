with seed as (
    select drug, reaction,
        a::float as a, b::float as b, c::float as c, d::float as d,
        expected_prr, expected_ror, expected_ror_ci_lower, expected_chi2_yates, expected_is_signal
    from {{ ref('signal_worked_example') }}
),
calc as (
    select drug, reaction, a,
        {{ metric_prr('a','b','c','d') }}          as prr,
        {{ metric_ror('a','b','c','d') }}          as ror,
        {{ metric_ror_ci_lower('a','b','c','d') }} as ror_ci_lower,
        {{ metric_chi2_yates('a','b','c','d') }}   as chi2_yates,
        expected_prr, expected_ror, expected_ror_ci_lower, expected_chi2_yates, expected_is_signal
    from seed
)
select * from calc
where abs(prr - expected_prr) > 0.001
   or abs(ror - expected_ror) > 0.001
   or abs(ror_ci_lower - expected_ror_ci_lower) > 0.001
   or abs(chi2_yates - expected_chi2_yates) > 0.001
   or coalesce(a >= {{ var('signal_min_cases') }}
        and prr >= {{ var('signal_min_prr') }}
        and chi2_yates >= {{ var('signal_min_chi2') }}, false) <> expected_is_signal
