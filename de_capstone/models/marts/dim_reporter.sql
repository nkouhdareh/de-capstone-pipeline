{{ config(materialized='table') }}

-- One row per distinct reporting context: reporter qualification + type + origin country.
-- reporter_key is the SAME surrogate hash computed in fct_report_drug_reaction, so the
-- fact needs no join and the FK holds by construction (NULLs handled by the macro).
with src as (
    select distinct
        reporter_qualification_code,
        reporter_type,
        occur_country
    from {{ ref('stg_drug_event') }}
)
select
    {{ dbt_utils.generate_surrogate_key(['reporter_qualification_code', 'reporter_type', 'occur_country']) }} as reporter_key,
    reporter_qualification_code,
    reporter_type,
    occur_country,
    '{{ invocation_id }}' as _run_id,
    {{ dbt.current_timestamp() }} as _loaded_at
from src
