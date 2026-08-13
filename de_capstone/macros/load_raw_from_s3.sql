{#
  Reload Snowflake RAW from the S3 external stages.

  TRUNCATE is a correctness requirement, not a preference: Snowflake tracks load
  metadata per file path, so a COPY alone would append a second full copy of the
  data (~90M rows). TRUNCATE clears that metadata; DELETE does not.

  Run by Airflow's load_raw task:  dbt run-operation load_raw_from_s3
#}

{% macro load_raw_from_s3() %}

  {% do log("TRUNCATE RAW.SILVER_DRUG_EVENT", info=True) %}
  {% do run_query("TRUNCATE TABLE DE_CAPSTONE.RAW.SILVER_DRUG_EVENT") %}

  {% do log("COPY INTO RAW.SILVER_DRUG_EVENT FROM @RAW.SILVER_PIPELINE_S3_STAGE", info=True) %}
  {% do run_query(
    "COPY INTO DE_CAPSTONE.RAW.SILVER_DRUG_EVENT
       FROM @DE_CAPSTONE.RAW.SILVER_PIPELINE_S3_STAGE
       FILE_FORMAT = (FORMAT_NAME = 'DE_CAPSTONE.RAW.FF_PARQUET')
       MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
       PATTERN = '.*[.]parquet'
       ON_ERROR = 'ABORT_STATEMENT'"
  ) %}

  {% do log("TRUNCATE RAW.DRUG_NDC", info=True) %}
  {% do run_query("TRUNCATE TABLE DE_CAPSTONE.RAW.DRUG_NDC") %}

  {% do log("COPY INTO RAW.DRUG_NDC FROM @RAW.NDC_S3_STAGE", info=True) %}
  {% do run_query(
    "COPY INTO DE_CAPSTONE.RAW.DRUG_NDC
       FROM @DE_CAPSTONE.RAW.NDC_S3_STAGE
       FILE_FORMAT = (FORMAT_NAME = 'DE_CAPSTONE.RAW.FF_JSON')
       ON_ERROR = 'ABORT_STATEMENT'"
  ) %}

  {% set silver = run_query("SELECT COUNT(*) FROM DE_CAPSTONE.RAW.SILVER_DRUG_EVENT") %}
  {% set ndc    = run_query("SELECT COUNT(*) FROM DE_CAPSTONE.RAW.DRUG_NDC") %}

  {% do log("RAW.SILVER_DRUG_EVENT rows: " ~ silver.columns[0].values()[0], info=True) %}
  {% do log("RAW.DRUG_NDC rows: "          ~ ndc.columns[0].values()[0],    info=True) %}

{% endmacro %}