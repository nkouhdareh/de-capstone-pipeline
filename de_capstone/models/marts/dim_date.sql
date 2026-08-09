{{ config(materialized='table') }}

-- Airflow-ready calendar: dates are derived from the data actually loaded (distinct
-- receive_date in the Silver source), so a future scheduled run that loads new months/
-- years extends dim_date automatically — no hardcoded window to maintain. date_key is
-- yyyymmdd, matching fct_report_drug_reaction.receive_date_key.
with dates as (
    select distinct receive_date as full_date
    from {{ ref('stg_drug_event') }}
    where receive_date is not null
)
select
    cast(to_char(full_date, 'YYYYMMDD') as integer) as date_key,
    full_date,
    year(full_date)                                 as year,
    quarter(full_date)                              as quarter,
    month(full_date)                                as month,
    monthname(full_date)                            as month_name,
    day(full_date)                                  as day_of_month,
    dayofweekiso(full_date)                         as iso_day_of_week,
    dayname(full_date)                              as day_name,
    weekiso(full_date)                              as iso_week,
    (dayofweekiso(full_date) in (6, 7))             as is_weekend,
    '{{ invocation_id }}' as _run_id,
    {{ dbt.current_timestamp() }} as _loaded_at
from dates
