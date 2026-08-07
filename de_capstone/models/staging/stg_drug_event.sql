with source as (
    select * from {{ source('raw', 'silver_drug_event') }}
)
select
    safety_report_id, report_drug_reaction_key, report_version,
    receive_date, receipt_date,
    medicinalproduct_raw, drug_name_clean, resolved_drug,
    drug_resolution_tier, drug_resolved,
    rxcui, product_ndc, package_ndc, brand_name,
    drug_characterization_code, drug_characterization,
    reaction_pt, reaction_meddra_version, reaction_outcome_code, reaction_outcome,
    is_serious, outcome_death, outcome_hospitalisation, outcome_life_threatening,
    outcome_disability, outcome_congenital_anomaly, outcome_other,
    reporter_qualification_code, reporter_type, occur_country, primary_source_country,
    patient_sex, patient_age_band,
    _run_id, _loaded_at
from source
