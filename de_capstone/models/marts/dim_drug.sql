{{ config(materialized='table') }}

with res as ( select * from {{ ref('int_drug_resolution') }} ),
resolved as (
    select
        canonical_drug_name,
        count(distinct resolved_drug) as n_source_names,
        min(case resolution_tier when 'rxcui' then 1 when 'generic' then 2
                 when 'brand' then 3 when 'ingredient' then 4 end) as best_tier_rank
    from res
    where is_resolved and canonical_drug_name is not null and canonical_drug_name <> ''
    group by canonical_drug_name
),
keyed as (
    select
        row_number() over (order by canonical_drug_name) as drug_key,
        canonical_drug_name as drug_name,
        n_source_names,
        case best_tier_rank when 1 then 'rxcui' when 2 then 'generic'
             when 3 then 'brand' when 4 then 'ingredient' end as primary_resolution_tier
    from resolved
)
select drug_key, drug_name, primary_resolution_tier, n_source_names, false as is_unknown,
       '{{ invocation_id }}' as _run_id, {{ dbt.current_timestamp() }} as _loaded_at
from keyed
union all
select -1, 'Unknown', null, null, true, '{{ invocation_id }}', {{ dbt.current_timestamp() }}
