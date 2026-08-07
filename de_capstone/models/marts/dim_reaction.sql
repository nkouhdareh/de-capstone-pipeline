{{ config(materialized='table') }}

with terms as (
    select distinct reaction_pt
    from {{ ref('stg_drug_event') }}
    where reaction_pt is not null and trim(reaction_pt) <> ''
)
select
    row_number() over (order by reaction_pt) as reaction_key,
    reaction_pt,
    '{{ invocation_id }}' as _run_id,
    {{ dbt.current_timestamp() }} as _loaded_at
from terms
