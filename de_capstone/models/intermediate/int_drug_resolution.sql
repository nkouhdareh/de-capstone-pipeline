{{ config(materialized='table') }}

with silver as (
    select distinct resolved_drug, rxcui, brand_name
    from {{ ref('stg_drug_event') }}
),
drugs as (
    select
        {{ dbt_utils.generate_surrogate_key(['resolved_drug', 'rxcui', 'brand_name']) }} as drug_nk,
        resolved_drug, rxcui, brand_name,
        {{ normalize_drug_name('resolved_drug') }} as resolved_drug_norm,
        {{ normalize_drug_name('brand_name') }}    as brand_name_norm
    from silver
),
ndc as ( select * from {{ ref('stg_drug_ndc') }} ),

-- rxcui -> generic (keep only rxcui that map to ONE generic)
ndc_rxcui_base as (
    select f.value::varchar as rxcui_code, {{ normalize_drug_name('n.generic_name') }} as canonical_name
    from ndc n, lateral flatten(input => n.rxcui_arr) f
    where f.value is not null and n.generic_name is not null
),
ndc_rxcui as (
    select rxcui_code, max(canonical_name) as canonical_name
    from ndc_rxcui_base where canonical_name <> ''
    group by rxcui_code having count(distinct canonical_name) = 1
),
-- generic name -> itself
ndc_generic as (
    select distinct {{ normalize_drug_name('generic_name') }} as name_norm,
                    {{ normalize_drug_name('generic_name') }} as canonical_name
    from ndc where generic_name is not null and {{ normalize_drug_name('generic_name') }} <> ''
),
-- brand -> generic (unambiguous only)
ndc_brand_base as (
    select {{ normalize_drug_name('brand_name') }} as name_norm, {{ normalize_drug_name('generic_name') }} as canonical_name
    from ndc where brand_name is not null and generic_name is not null
),
ndc_brand as (
    select name_norm, max(canonical_name) as canonical_name
    from ndc_brand_base where name_norm <> '' and canonical_name <> ''
    group by name_norm having count(distinct canonical_name) = 1
),
-- active ingredient -> itself
ndc_ingredient as (
    select distinct {{ normalize_drug_name('ai.value:name::varchar') }} as name_norm,
                    {{ normalize_drug_name('ai.value:name::varchar') }} as canonical_name
    from ndc n, lateral flatten(input => n.active_ingredients) ai
    where ai.value:name is not null and {{ normalize_drug_name('ai.value:name::varchar') }} <> ''
),
matched as (
    select d.drug_nk, d.resolved_drug, d.rxcui, d.brand_name,
        rx.canonical_name as rxcui_match, ge.canonical_name as generic_match,
        br.canonical_name as brand_match, ing.canonical_name as ingredient_match
    from drugs d
    left join ndc_rxcui     rx  on d.rxcui = rx.rxcui_code and d.rxcui is not null and d.rxcui <> ''
    left join ndc_generic   ge  on d.resolved_drug_norm = ge.name_norm and d.resolved_drug_norm <> ''
    left join ndc_brand     br  on d.brand_name_norm = br.name_norm and d.brand_name_norm <> ''
    left join ndc_ingredient ing on d.resolved_drug_norm = ing.name_norm and d.resolved_drug_norm <> ''
)
select
    drug_nk, resolved_drug, rxcui, brand_name,
    coalesce(rxcui_match, generic_match, brand_match, ingredient_match) as canonical_drug_name,
    case
        when rxcui_match      is not null then 'rxcui'
        when generic_match    is not null then 'generic'
        when brand_match      is not null then 'brand'
        when ingredient_match is not null then 'ingredient'
        else 'unresolved'
    end as resolution_tier,
    (coalesce(rxcui_match, generic_match, brand_match, ingredient_match) is not null) as is_resolved
from matched
