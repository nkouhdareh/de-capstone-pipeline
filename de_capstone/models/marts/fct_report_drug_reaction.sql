{{ config(materialized='table', cluster_by=['receive_date']) }}

with events as (
    select *,
        {{ dbt_utils.generate_surrogate_key(['resolved_drug', 'rxcui', 'brand_name']) }} as drug_nk
    from {{ ref('stg_drug_event') }}
),
res as ( select drug_nk, canonical_drug_name, resolution_tier from {{ ref('int_drug_resolution') }} ),
d_drug as ( select drug_key, drug_name from {{ ref('dim_drug') }} ),
d_reaction as ( select reaction_key, reaction_pt from {{ ref('dim_reaction') }} ),
d_reporter as ( select reporter_key, reporter_qualification_code, reporter_type, occur_country from {{ ref('dim_reporter') }} ),
d_date as ( select date_key, full_date from {{ ref('dim_date') }} )
select
    e.report_drug_reaction_key,
    e.safety_report_id,
    coalesce(dd.drug_key, -1) as drug_key,
    rk.reaction_key,
    dr.reporter_key,
    dt.date_key as receive_date_key,
    e.receive_date,
    e.drug_characterization as drug_characterisation,
    r.resolution_tier as drug_resolution_tier,
    e.is_serious,
    e.outcome_death, e.outcome_hospitalisation, e.outcome_life_threatening,
    e.outcome_disability, e.outcome_congenital_anomaly, e.outcome_other,
    e.patient_age_band, e.patient_sex, e.report_version,
    '{{ invocation_id }}' as _run_id,
    {{ dbt.current_timestamp() }} as _loaded_at
from events e
left join res r         on e.drug_nk = r.drug_nk
left join d_drug dd      on r.canonical_drug_name = dd.drug_name
left join d_reaction rk  on e.reaction_pt = rk.reaction_pt
left join d_reporter dr
    on  equal_null(e.reporter_qualification_code, dr.reporter_qualification_code)
    and equal_null(e.reporter_type,               dr.reporter_type)
    and equal_null(e.occur_country,               dr.occur_country)
left join d_date dt      on e.receive_date = dt.full_date
