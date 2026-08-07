{{ config(materialized='table') }}

-- Complete calendar for the FAERS 2023-2024 window (date_spine end is exclusive).
-- date_key is yyyymmdd, identical to fct_report_drug_reaction.receive_date_key.
with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="to_date('2023-01-01')",
        end_date="to_date('2025-01-01')"
    ) }}
)
select
    cast(to_char(date_day, 'YYYYMMDD') as integer) as date_key,
    date_day                                       as full_date,
    year(date_day)                                 as year,
    quarter(date_day)                              as quarter,
    month(date_day)                                as month,
    monthname(date_day)                            as month_name,
    day(date_day)                                  as day_of_month,
    dayofweekiso(date_day)                         as iso_day_of_week,
    dayname(date_day)                              as day_name,
    weekiso(date_day)                              as iso_week,
    (dayofweekiso(date_day) in (6, 7))             as is_weekend,
    '{{ invocation_id }}' as _run_id,
    {{ dbt.current_timestamp() }} as _loaded_at
from spine
