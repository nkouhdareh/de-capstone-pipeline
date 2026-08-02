# Job Market Tool Demand — German Data Engineering Roles

**Method:** 16 unique job advertisements collected manually from StepStone (Germany,
mixed Munich / Berlin / remote), July 2026. Text analysed for tool and skill
mentions with word-boundary regular expressions. Counted as *ads mentioning*,
not raw occurrences.

**Data quality note:** 20 ads were collected; 4 were exact duplicates and were
removed before analysis (n = 20 → 16).

**Limitations:** small sample, self-selected, not statistically representative.
Directional evidence only. Some patterns are broad (e.g. "governance", "API").
Ads are mixed German and English.

---

## Results

| Tool / Skill | Ads | % |
|---|---:|---:|
| Python | 13 | 81% |
| SQL | 13 | 81% |
| ETL / ELT | 11 | 69% |
| Data Modeling | 10 | 62% |
| **Azure** | 10 | **62%** |
| Monitoring / Observability | 9 | 56% |
| Data Warehouse / DWH | 8 | 50% |
| Spark / PySpark | 8 | 50% |
| Data Quality | 7 | 44% |
| Databricks | 7 | 44% |
| AWS | 7 | 44% |
| Microsoft Fabric | 7 | 44% |
| CI/CD | 7 | 44% |
| GCP | 6 | 38% |
| ML / Data Science adjacency | 6 | 38% |
| dbt | 5 | 31% |
| Airflow | 5 | 31% |
| Docker | 5 | 31% |
| Power BI | 5 | 31% |
| REST / API | 5 | 31% |
| Postgres | 4 | 25% |
| Lakehouse / Medallion / Data Lake | 4 | 25% |
| Kafka | 4 | 25% |
| Kubernetes | 4 | 25% |
| Streaming / real-time | 4 | 25% |
| Terraform | 4 | 25% |
| MongoDB | 3 | 19% |
| **Snowflake** | 3 | **19%** |
| Git / GitHub / GitLab | 3 | 19% |
| Data Governance | 3 | 19% |
| MLOps | 3 | 19% |
| Scala | 3 | 19% |
| SQLMesh | 2 | 12% |
| Airbyte | 2 | 12% |
| BigQuery | 2 | 12% |
| Automated testing | 2 | 12% |
| DuckDB | 2 | 12% |
| LLM / GenAI | 2 | 12% |
| **RAG / vector databases** | 2 | **12%** |
| Pandas | 2 | 12% |
| Java | 2 | 12% |
| Flink | 2 | 12% |
| Redshift | 1 | 6% |
| MySQL | 1 | 6% |

---

## Five findings that change decisions

### 1. Azure leads AWS in this sample (62% vs 44%)

The German market in this sample is more Microsoft-oriented than the bootcamp
curriculum assumes. Microsoft Fabric (44%) appears more than twice as often as
Snowflake (19%).

*Relevance:* I hold a Microsoft Certified Azure Data Scientist Associate (DP-100)
and spent four years on the Microsoft stack at Siemens Healthineers. That
experience is more market-aligned than I had assumed and should be foregrounded
in applications.

*Capstone decision:* still build on AWS, because I have $182 in AWS credits and
no Azure credits, and because the bootcamp covered AWS. Document the trade-off
in an ADR rather than leaving it implicit.

### 2. Snowflake is weaker than expected (19%)

Snowflake appeared in only 3 of 16 ads, behind Databricks (44%) and Fabric (44%).

*Capstone decision:* do not architect around the one-month Snowflake trial.
Postgres or DuckDB with dbt is defensible and removes an expiry risk. dbt itself
(31%) is worth keeping regardless of the warehouse underneath.

### 3. Practices outrank tools

Aggregating the non-tool entries: ETL/ELT 69%, data modeling 62%, monitoring 56%,
data warehousing 50%, data quality 44%, CI/CD 44%.

These are engineering *disciplines*, not products — and they are exactly what the
capstone rubric assesses ("design, build, and justify"). Market demand and grading
criteria point the same direction: pipeline rigour beats tool collection.

*Capstone decision:* invest in orchestration, testing, error handling, monitoring
and documentation before adding any further tool.

### 4. RAG appears in data engineering job descriptions, not just ML roles

2 of 16 ads (12%), and the phrasing is explicit about it being a data engineering
responsibility:

> "designing context/retrieval layers (e.g., RAG systems) and feedback loops for
> AI/LLM applications"

> "Sie bauen Vektordatenbanken (RAG) und Graph-Systeme auf und pflegen diese
> dauerhaft ... praktische Erfahrung mit Datenbankintegration, Vektordatenbanken
> und RAG-Systemen"

> "optimized retrieval interfaces to ground LLM/AI outputs"

*Capstone decision:* this validates RAG as a differentiator — 12% is enough to be
a genuine edge, and low enough that it should not displace core pipeline work.
Keep it as the time-boxed extension after the pipeline is complete.

### 5. Streaming is real but not dominant (Kafka 25%, streaming 25%)

*Capstone decision:* a batch-only pipeline with a written justification is
defensible. A contrived streaming layer is not worth the risk in a three-week
project. Document as an ADR.

---

## Tool choices this evidence supports

| Layer | Choice | Evidence |
|---|---|---|
| Language | Python + SQL | 81% each — non-negotiable |
| Transformation | dbt | 31%, and pairs with the warehouse |
| Orchestration | Airflow | 31%, highest of any orchestrator |
| Warehouse | Postgres / DuckDB | Postgres 25%; avoids trial-expiry risk |
| Cloud | AWS | 44%, and credits available |
| Containers | Docker | 31% |
| IaC | Terraform | 25%, if time allows |
| Vector store | pgvector | RAG 12%, and reuses Postgres |
| Serving | Power BI or Streamlit | Power BI 31% |
