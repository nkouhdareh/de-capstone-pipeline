import argparse
import datetime
import os
import sys

os.environ["PYSPARK_SUBMIT_ARGS"] = "--driver-memory 4g pyspark-shell"

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.window import Window


BRONZE_DIR = os.environ.get(
    "BRONZE_DIR",
    "/home/jovyan/data/bronze/drug_event",
)

CACHE_DIR = os.environ.get(
    "CACHE_DIR",
    "/home/jovyan/dq_cache/drug_event",
)

SILVER_OUT = os.environ.get("SILVER_OUT")
QUAR_OUT = os.environ.get("QUAR_OUT")
SILVER_METRICS = os.environ.get("SILVER_METRICS")

if not SILVER_OUT or not QUAR_OUT or not SILVER_METRICS:
    raise RuntimeError(
        "Set SILVER_OUT, QUAR_OUT, and SILVER_METRICS explicitly. "
        "This prevents accidental overwriting of existing outputs."
    )


SEX = {
    "0": "Unknown",
    "1": "Male",
    "2": "Female",
}

CHARACTERIZATION = {
    "1": "SUSPECT",
    "2": "CONCOMITANT",
    "3": "INTERACTING",
}

VALID_CHAR = ["1", "2", "3"]

OUTCOME = {
    "1": "Recovered/resolved",
    "2": "Recovering/resolving",
    "3": "Not recovered/not resolved",
    "4": "Recovered with sequelae",
    "5": "Fatal",
    "6": "Unknown",
}

QUALIFICATION = {
    "1": "Physician",
    "2": "Pharmacist",
    "3": "Other health professional",
    "4": "Lawyer",
    "5": "Consumer or non-health professional",
}

GRAIN = [
    "safety_report_id",
    "resolved_drug",
    "drug_characterization_code",
    "reaction_pt",
]

SLIM_DRUGS = (
    "transform(patient.drug, d -> struct("
    "d.medicinalproduct as medicinalproduct, "
    "d.drugcharacterization as drugcharacterization, "
    "element_at(d.openfda.generic_name, 1) as generic_name, "
    "element_at(d.openfda.substance_name, 1) as substance_name, "
    "element_at(d.openfda.rxcui, 1) as rxcui, "
    "element_at(d.openfda.product_ndc, 1) as product_ndc, "
    "element_at(d.openfda.package_ndc, 1) as package_ndc, "
    "element_at(d.openfda.brand_name, 1) as brand_name))"
)


def decode(column, mapping, default=None):
    items = list(mapping.items())

    expression = F.when(
        column == items[0][0],
        F.lit(items[0][1]),
    )

    for code, label in items[1:]:
        expression = expression.when(
            column == code,
            F.lit(label),
        )

    return expression.otherwise(F.lit(default).cast("string"))


def flag(column_name):
    return F.when(
        F.col(column_name) == "1",
        True,
    ).otherwise(False)


def create_spark_session():
    return (
        SparkSession.builder
        .appName("openfda_silver_python_job")
        .config("spark.driver.memory", "4g")
        .config("spark.sql.shuffle.partitions", "64")
        .config("spark.sql.parquet.enableVectorizedReader", "false")
        .config("spark.local.dir", "/opt/spark-tmp")
        .config(
            "spark.sql.sources.partitionOverwriteMode",
            "dynamic",
        )
        .getOrCreate()
    )


def month_prefix(year, month):
    return f"{year}{month:02d}"


def parse_months(value):
    value = value.strip().lower()

    if value == "all":
        return [
            (year, month)
            for year in (2023, 2024)
            for month in range(1, 13)
        ]

    result = []

    for item in value.split(","):
        year_text, month_text = item.strip().split("-")
        result.append((int(year_text), int(month_text)))

    return result


def build_cache(spark, months):
    for year, month in months:
        cache_partition = (
            f"{CACHE_DIR}/receive_year={year}/receive_month={month}"
        )

        if os.path.isdir(cache_partition):
            print("Cache already exists:", month_prefix(year, month))
            continue

        source_path = (
            f"{BRONZE_DIR}/receivedate="
            f"{month_prefix(year, month)}*/*.json"
        )

        try:
            month_df = spark.read.json(source_path)
        except Exception:
            print("No Bronze files found:", year, month)
            continue

        (
            month_df
            .withColumn("receive_year", F.lit(year))
            .withColumn("receive_month", F.lit(month))
            .write
            .mode("overwrite")
            .partitionBy("receive_year", "receive_month")
            .parquet(CACHE_DIR)
        )

        print("Cached:", month_prefix(year, month))


def build_month(month_df, run_id):
    latest_version_window = (
        Window
        .partitionBy("safetyreportid")
        .orderBy(
            F.col("safetyreportversion")
            .cast("int")
            .desc_nulls_last()
        )
    )

    month_df = (
        month_df
        .withColumn(
            "_row_number",
            F.row_number().over(latest_version_window),
        )
        .filter(F.col("_row_number") == 1)
        .drop("_row_number")
    )

    reports = month_df.select(
        F.col("safetyreportid").alias("safety_report_id"),
        F.col("safetyreportversion")
        .cast("int")
        .alias("report_version"),
        F.to_date("receivedate", "yyyyMMdd").alias("receive_date"),
        F.to_date("receiptdate", "yyyyMMdd").alias("receipt_date"),
        F.col("serious"),
        F.col("seriousnessdeath"),
        F.col("seriousnesshospitalization"),
        F.col("seriousnesslifethreatening"),
        F.col("seriousnessdisabling"),
        F.col("seriousnesscongenitalanomali"),
        F.col("seriousnessother"),
        F.col("primarysource.qualification")
        .alias("reporter_qualification_code"),
        F.col("occurcountry").alias("occur_country"),
        F.col("primarysourcecountry")
        .alias("primary_source_country"),
        F.col("patient.patientsex").alias("patientsex"),
        F.col("patient.patientonsetage").alias("patientonsetage"),
        F.col("patient.patientonsetageunit")
        .alias("patientonsetageunit"),
        F.expr(SLIM_DRUGS).alias("drugs"),
        F.col("patient.reaction").alias("reactions"),
    )

    drug_rows = (
        reports
        .select(
            "*",
            F.posexplode("drugs").alias("drug_idx", "drug"),
        )
        .drop("drugs")
    )

    drug_characterization = F.col(
        "drug.drugcharacterization"
    )

    drug_name = F.col("drug.medicinalproduct")

    drug_reject_reason = (
        F.when(
            drug_characterization.isNull(),
            F.lit("drugcharacterization_null"),
        )
        .when(
            ~drug_characterization.isin(*VALID_CHAR),
            F.lit("drugcharacterization_out_of_range"),
        )
        .when(
            drug_name.isNull() | (F.trim(drug_name) == ""),
            F.lit("drug_name_blank"),
        )
        .otherwise(F.lit(None).cast("string"))
    )

    drug_rows = drug_rows.withColumn(
        "_drug_reject_reason",
        drug_reject_reason,
    )

    quarantined_drugs = (
        drug_rows
        .filter(F.col("_drug_reject_reason").isNotNull())
        .select(
            "safety_report_id",
            "report_version",
            drug_name.alias("medicinalproduct_raw"),
            drug_characterization.alias(
                "drug_characterization_code"
            ),
            F.lit(None).cast("string").alias("reaction_pt"),
            F.col("_drug_reject_reason").alias("_reject_reason"),
            F.year("receive_date").alias("receive_year"),
            F.month("receive_date").alias("receive_month"),
        )
    )

    valid_drugs = (
        drug_rows
        .filter(F.col("_drug_reject_reason").isNull())
        .drop("_drug_reject_reason")
        .repartition(
            64,
            F.col("safety_report_id"),
            F.col("drug_idx"),
        )
    )

    atomic_rows = (
        valid_drugs
        .select(
            "*",
            F.explode("reactions").alias("reaction"),
        )
        .drop("reactions")
    )

    reaction_pt = F.col("reaction.reactionmeddrapt")

    quarantined_reactions = (
        atomic_rows
        .filter(
            reaction_pt.isNull()
            | (F.trim(reaction_pt) == "")
        )
        .select(
            "safety_report_id",
            "report_version",
            F.col("drug.medicinalproduct")
            .alias("medicinalproduct_raw"),
            drug_characterization.alias(
                "drug_characterization_code"
            ),
            reaction_pt.alias("reaction_pt"),
            F.lit("reaction_pt_null")
            .alias("_reject_reason"),
            F.year("receive_date").alias("receive_year"),
            F.month("receive_date").alias("receive_month"),
        )
    )

    quarantine = quarantined_drugs.unionByName(
        quarantined_reactions
    )

    good_rows = atomic_rows.filter(
        ~(
            reaction_pt.isNull()
            | (F.trim(reaction_pt) == "")
        )
    )

    raw_drug_name = F.col("drug.medicinalproduct")
    generic_name = F.col("drug.generic_name")
    substance_name = F.col("drug.substance_name")

    name_upper = F.upper(raw_drug_name)

    name_without_dose = F.regexp_replace(
        name_upper,
        "[0-9]+ ?(MG|MCG|UG|G|GM|ML|L|IU|MEQ|MMOL|UNITS|UNIT|%)",
        " ",
    )

    clean_drug_name = F.trim(
        F.regexp_replace(
            F.regexp_replace(
                name_without_dose,
                "[^A-Z0-9 ]",
                " ",
            ),
            " +",
            " ",
        )
    )

    resolved_drug = (
        F.when(
            generic_name.isNotNull()
            & (F.trim(generic_name) != ""),
            F.upper(F.trim(generic_name)),
        )
        .when(
            substance_name.isNotNull()
            & (F.trim(substance_name) != ""),
            F.upper(F.trim(substance_name)),
        )
        .otherwise(clean_drug_name)
    )

    resolution_tier = (
        F.when(
            generic_name.isNotNull()
            & (F.trim(generic_name) != ""),
            F.lit("generic_name"),
        )
        .when(
            substance_name.isNotNull()
            & (F.trim(substance_name) != ""),
            F.lit("substance_name"),
        )
        .otherwise(F.lit("unresolved_raw"))
    )

    age = F.col("patientonsetage").cast("double")
    age_unit = F.col("patientonsetageunit")

    age_years = (
        F.when(age_unit == "800", age * 10)
        .when((age_unit == "801") | age_unit.isNull(), age)
        .when(age_unit == "802", age / 12)
        .when(age_unit == "803", age / 52)
        .when(age_unit == "804", age / 365)
        .when(age_unit == "805", age / 8760)
        .otherwise(F.lit(None))
    )

    age_band = (
        F.when(
            age_years.isNull()
            | (age_years < 0)
            | (age_years > 120),
            F.lit("Unknown"),
        )
        .when(age_years < 18, F.lit("0-17"))
        .when(age_years < 45, F.lit("18-44"))
        .when(age_years < 65, F.lit("45-64"))
        .when(age_years < 75, F.lit("65-74"))
        .otherwise(F.lit("75+"))
    )

    silver = good_rows.select(
        F.col("safety_report_id"),
        F.col("report_version"),
        F.col("receive_date"),
        F.col("receipt_date"),
        raw_drug_name.alias("medicinalproduct_raw"),
        clean_drug_name.alias("drug_name_clean"),
        resolved_drug.alias("resolved_drug"),
        resolution_tier.alias("drug_resolution_tier"),
        (resolution_tier != "unresolved_raw")
        .alias("drug_resolved"),
        F.col("drug.rxcui").alias("rxcui"),
        F.col("drug.product_ndc").alias("product_ndc"),
        F.col("drug.package_ndc").alias("package_ndc"),
        F.col("drug.brand_name").alias("brand_name"),
        drug_characterization.alias(
            "drug_characterization_code"
        ),
        decode(
            drug_characterization,
            CHARACTERIZATION,
        ).alias("drug_characterization"),
        F.col("reaction.reactionmeddrapt")
        .alias("reaction_pt"),
        F.col("reaction.reactionmeddraversionpt")
        .alias("reaction_meddra_version"),
        F.col("reaction.reactionoutcome")
        .alias("reaction_outcome_code"),
        decode(
            F.col("reaction.reactionoutcome"),
            OUTCOME,
        ).alias("reaction_outcome"),
        (
            F.when(F.col("serious") == "1", True)
            .when(F.col("serious") == "2", False)
            .otherwise(F.lit(None).cast("boolean"))
        ).alias("is_serious"),
        flag("seriousnessdeath").alias("outcome_death"),
        flag("seriousnesshospitalization")
        .alias("outcome_hospitalisation"),
        flag("seriousnesslifethreatening")
        .alias("outcome_life_threatening"),
        flag("seriousnessdisabling")
        .alias("outcome_disability"),
        flag("seriousnesscongenitalanomali")
        .alias("outcome_congenital_anomaly"),
        flag("seriousnessother")
        .alias("outcome_other"),
        F.col("reporter_qualification_code"),
        decode(
            F.col("reporter_qualification_code"),
            QUALIFICATION,
        ).alias("reporter_type"),
        F.coalesce(
            F.col("occur_country"),
            F.lit("Unknown"),
        ).alias("occur_country"),
        F.coalesce(
            F.col("primary_source_country"),
            F.lit("Unknown"),
        ).alias("primary_source_country"),
        F.coalesce(
            decode(F.col("patientsex"), SEX),
            F.lit("Unknown"),
        ).alias("patient_sex"),
        age_band.alias("patient_age_band"),
        F.year("receive_date").alias("receive_year"),
        F.month("receive_date").alias("receive_month"),
        F.lit(run_id).alias("_run_id"),
        F.current_timestamp().alias("_loaded_at"),
        F.sha2(
            F.concat_ws(
                "||",
                F.col("safety_report_id"),
                resolved_drug,
                drug_characterization,
                F.col("reaction.reactionmeddrapt"),
            ),
            256,
        ).alias("report_drug_reaction_key"),
    )

    return silver, quarantine


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--months",
        required=True,
        help="Examples: 2023-01, 2023-01,2023-02, or all",
    )

    arguments = parser.parse_args()

    months = parse_months(arguments.months)

    run_id = (
        "silver_"
        + datetime.datetime.utcnow()
        .strftime("%Y%m%dT%H%M%SZ")
    )

    print("RUN_ID:", run_id)
    print("MONTHS:", months)
    print("SILVER_OUT:", SILVER_OUT)
    print("QUAR_OUT:", QUAR_OUT)
    print("SILVER_METRICS:", SILVER_METRICS)

    spark = create_spark_session()

    try:
        build_cache(spark, months)

        month_statistics = []

        for year, month in months:
            cache_partition = (
                f"{CACHE_DIR}/receive_year={year}"
                f"/receive_month={month}"
            )

            if not os.path.isdir(cache_partition):
                print("No cache partition:", year, month)
                continue

            month_df = spark.read.parquet(cache_partition)

            silver_month, quarantine_month = build_month(
                month_df,
                run_id,
            )
            silver_month = silver_month.persist()
            atomic_count = silver_month.count()

            (
                silver_month
                .dropDuplicates(GRAIN)
                .write
                .mode("overwrite")
                .partitionBy(
                    "receive_year",
                    "receive_month",
                )
                .parquet(SILVER_OUT)
            )
            quarantine_month = quarantine_month.persist()
            quarantine_count = quarantine_month.count()

            (
                quarantine_month
                .write
                .mode("overwrite")
                .partitionBy(
                    "receive_year",
                    "receive_month",
                )
                .parquet(QUAR_OUT)
            )
            silver_month.unpersist(); quarantine_month.unpersist()
            month_statistics.append(
                (
                    year,
                    month,
                    int(atomic_count),
                    int(quarantine_count),
                )
            )

            print(
                "Silver written:",
                year,
                month,
                "| atomic:",
                atomic_count,
                "| quarantined:",
                quarantine_count,
            )

        if not month_statistics:
            raise RuntimeError(
                "No requested month was processed."
            )

        requested_month_filter = None

        for year, month in months:
            condition = (
                (F.col("receive_year") == year)
                & (F.col("receive_month") == month)
            )

            if requested_month_filter is None:
                requested_month_filter = condition
            else:
                requested_month_filter = (
                    requested_month_filter | condition
                )

        silver_all = spark.read.parquet(SILVER_OUT)

        silver_requested = silver_all.filter(
            requested_month_filter
        )

        per_month = (
            silver_requested
            .groupBy(
                "receive_year",
                "receive_month",
            )
            .agg(
                F.count(F.lit(1)).alias("silver_rows"),
                F.sum(
                    F.col("drug_resolved").cast("int")
                ).alias("resolved_rows"),
            )
        )

        statistics_df = spark.createDataFrame(
            month_statistics,
            [
                "receive_year",
                "receive_month",
                "atomic_rows",
                "quarantined_rows",
            ],
        )

        metrics = (
            statistics_df
            .join(
                per_month,
                [
                    "receive_year",
                    "receive_month",
                ],
                "left",
            )
            .withColumn(
                "duplicates_removed",
                F.col("atomic_rows")
                - F.col("silver_rows"),
            )
            .withColumn("run_id", F.lit(run_id))
            .withColumn(
                "run_timestamp",
                F.current_timestamp(),
            )
        )

        (
            metrics
            .write
            .mode("overwrite")
            .parquet(SILVER_METRICS)
        )

        print(
            "Requested-month Silver rows:",
            silver_requested.count(),
        )

    finally:
        spark.stop()


if __name__ == "__main__":
    main()