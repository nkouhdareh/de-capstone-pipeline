{#
  Log the headline numbers at the end of a pipeline run, so every DAG run
  leaves an auditable record of what it produced.

  Run by Airflow's publish_metrics task:  dbt run-operation publish_metrics
#}

{% macro publish_metrics() %}

  {% set checks = [
    ("fct_report_drug_reaction rows", "SELECT COUNT(*) FROM DE_CAPSTONE.DBT_DEV.FCT_REPORT_DRUG_REACTION"),
    ("dim_drug rows",                 "SELECT COUNT(*) FROM DE_CAPSTONE.DBT_DEV.DIM_DRUG"),
    ("dim_reaction rows",             "SELECT COUNT(*) FROM DE_CAPSTONE.DBT_DEV.DIM_REACTION"),
    ("drug-reaction pairs",           "SELECT COUNT(*) FROM DE_CAPSTONE.DBT_DEV.SEM_SIGNAL_METRICS"),
    ("signals (is_signal)",           "SELECT SUM(IFF(is_signal, 1, 0)) FROM DE_CAPSTONE.DBT_DEV.SEM_SIGNAL_METRICS"),
    ("signals (is_signal_strict)",    "SELECT SUM(IFF(is_signal_strict, 1, 0)) FROM DE_CAPSTONE.DBT_DEV.SEM_SIGNAL_METRICS")
  ] %}

  {% for label, sql in checks %}
    {% set result = run_query(sql) %}
    {% do log(label ~ ": " ~ result.columns[0].values()[0], info=True) %}
  {% endfor %}

{% endmacro %}