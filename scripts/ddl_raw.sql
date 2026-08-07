-- =====================================================================
-- RAW landing objects for the PV signal pipeline.
-- Executed by scripts/snowflake/load_to_snowflake.py. No secrets here.
-- Idempotent (IF NOT EXISTS); the loader TRUNCATEs + reloads per target.
-- =====================================================================
USE DATABASE DE_CAPSTONE;
USE SCHEMA RAW;

-- ---- file formats ----
CREATE FILE FORMAT IF NOT EXISTS RAW.FF_PARQUET TYPE = PARQUET;
CREATE FILE FORMAT IF NOT EXISTS RAW.FF_JSON    TYPE = JSON STRIP_OUTER_ARRAY = FALSE;

-- ---- internal named stages ----
CREATE STAGE IF NOT EXISTS RAW.SILVER_STAGE FILE_FORMAT = RAW.FF_PARQUET;
CREATE STAGE IF NOT EXISTS RAW.NDC_STAGE    FILE_FORMAT = RAW.FF_JSON;

-- ---- RAW.SILVER_DRUG_EVENT ------------------------------------------------
-- The clean atomic Silver (grain: case x resolved drug x characterization x
-- reaction). receive_year/receive_month are Spark partition columns encoded in
-- the Parquet directory path (NOT in the files), so they are omitted here and
-- recomputed from receive_date downstream.
CREATE TABLE IF NOT EXISTS RAW.SILVER_DRUG_EVENT (
  safety_report_id            VARCHAR,
  report_version              NUMBER,
  receive_date                DATE,
  receipt_date                DATE,
  medicinalproduct_raw        VARCHAR,
  drug_name_clean             VARCHAR,
  resolved_drug               VARCHAR,
  drug_resolution_tier        VARCHAR,
  drug_resolved               BOOLEAN,
  rxcui                       VARCHAR,
  product_ndc                 VARCHAR,
  package_ndc                 VARCHAR,
  brand_name                  VARCHAR,
  drug_characterization_code  VARCHAR,
  drug_characterization       VARCHAR,
  reaction_pt                 VARCHAR,
  reaction_meddra_version     VARCHAR,
  reaction_outcome_code       VARCHAR,
  reaction_outcome            VARCHAR,
  is_serious                  BOOLEAN,
  outcome_death               BOOLEAN,
  outcome_hospitalisation     BOOLEAN,
  outcome_life_threatening    BOOLEAN,
  outcome_disability          BOOLEAN,
  outcome_congenital_anomaly  BOOLEAN,
  outcome_other               BOOLEAN,
  reporter_qualification_code VARCHAR,
  reporter_type               VARCHAR,
  occur_country               VARCHAR,
  primary_source_country      VARCHAR,
  patient_sex                 VARCHAR,
  patient_age_band            VARCHAR,
  _run_id                     VARCHAR,
  _loaded_at                  TIMESTAMP_NTZ,
  report_drug_reaction_key    VARCHAR
);

-- ---- RAW.DRUG_NDC ---------------------------------------------------------
-- openFDA NDC product directory as NDJSON: one VARIANT row per product.
-- Flattened in dbt stg_drug_ndc (the one model with Snowflake-specific FLATTEN).
CREATE TABLE IF NOT EXISTS RAW.DRUG_NDC (
  v VARIANT
);
