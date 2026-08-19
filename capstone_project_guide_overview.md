
# Data Engineering Capstone Project Guide

This document outlines the step-by-step process overview that can guide for successfully completing your Data Engineering (DE) Capstone Project.

To ensure your project is manageable and industry-relevant, you must choose **one of two paths** to begin: **Path A (Domain-Driven)** or **Path B (Job-Market Driven)**. After completing the initial steps of your chosen path, you will merge into the Core Execution Workflow.

**Instructor & TA Support:**
* Instructors are available daily between **09:30 and 18:30** in weekdays
* TA are available daily between **09:00 and 18:00** in weekdays
* We use Discord for communication and quick queries. If a longer discussion or screen-share is needed, Zoom session(s) will be conducted accordingly.

---

## Project Management, Version Control & Support

Before you begin, you must set up your project management and version control infrastructure.

* **Project Management Tool:** **GitHub Projects** (or Trello). GitHub Projects is highly accepted in the tech industry, integrates directly with your code repository, and utilizes a simple Kanban board interface.
* **Version Control:** You **must** create a Git repository (e.g., on GitHub) for this project. Commit your code frequently with clear, descriptive commit messages.

### Required Documentation
Your repository must include the following core documentation files:
1. **`README.md`**: Project overview, business problem, tech stack, and step-by-step setup instructions.
2. **`architecture.md`**: Visual diagram and written explanation of your data architecture, pipelines, and tool choices.
3. **`runbook.md`**: An operational manual detailing how to execute the pipeline, handle failures, and manage the environment.
4. **Architecture Decision Records (ADRs)**: Stored in `docs/adr/`, these document *why* you made specific technical decisions. For e.g., "Why we chose dbt for SQL-based transformations instead of Apache Spark?".

---

## Phase 1: Choose Your Starting Path

### Path A: Domain-Driven
Choose this path if you already have an interest in a specific industry or business problem.
1. **Find a Domain & Data:** Identify a domain you are interested in that has free and open-source data available via API, files or data streams.
2. **Identify the Business Problem:** Define a business problem that requires a data engineering solution (e.g., building a data pipeline or an analytics platform to serve downstream users for specific insight processing and deliveries).

### Path B: Job-Market Driven
Choose this path if you do not have a specific business domain in mind and want to tailor your project from bottom-to-top based only current job market demands.
1. **Research the Job Market:** Scan atleast 10-50 Data Engineering job descriptions. Research and report on the key job responsibilities and the most frequently mentioned tool stacks.
2. **Frame the Architecture:** Design a high-level architectural roadmap for the project that covers the most common responsibilities found in your research. Select a specific tool stack from your filtered list to implement this architecture.
3. **Find Data Sources:** Find suitable data sources that allow you to implement your architecture end-to-end (from ingestion to the serving layer).

**Note:** *Instructor/TA may assist you in finding these data sources. Check the [Appendix](#appendix-recommended-open-data-sources) for initial exploration. Common data engineering and relevant utility tools that are used for development and implementation can be explored [here](#appendix-technology-stacks).*

---

## Phase 2: Core Execution Workflow
Regardless of the path chosen above, all students must follow these steps below:

### Requirements Gathering & Approval
* **Business Requirements:** Gather your business requirements into a formal document. **Consult with your Instructor and TAs** for approval.
* **Technical Requirements:** Once business requirements are approved, identify the technical requirements needed to solve the problem. **Consult with your Instructor and TAs** again.
* **Architecture Design:** If technical requirements are approved, create the architecture for your solution (to be stored in `architecture.md`).

***Important Note:** Your project can be implemented **completely on the cloud** (end-to-end), **completely locally**, or as a **hybrid setup** (e.g., local processing pushing to a cloud data warehouse). This decision should be documented in your ADRs.*

 **Consult with your Instructor and TAs** for final sign-off.

### Core Implementation Phase
If not already started, initiate coding now. Agentic development or AI-assisted coding (e.g., Copilot, ChatGPT) is completely acceptable and encouraged for productivity.

**Minimum Criteria for Technical Execution:**
To pass the technical execution phase, your project should meet the minimum industry best practices and approaches:

1. **Data Ingestion:** A scripted or orchestrated pipeline that pulls data from your data source(s) into a raw storage layer.
2. **Data Transformation:** Implementation of a processing layer (via dbt, Spark, Polars, or Pandas etc ) that cleans, validates, and transforms the raw data in different phases
3.  **Data Architecture, Modeling, and Serving Strategy:**
    Define a scalable, maintainable, and business-aligned data architecture that supports reliable data processing, consistent analytics, and efficient data consumption.
     *  Organize data layers using appropriate frameworks (e.g., **Medallion Architecture** or **Data Vault**).
     *  Select a pipeline architecture pattern (e.g., **Lambda**, **Kappa**, or a suitable variation) that best fits the project’s batch and/or streaming, latency, and scalability requirements.
     * Model the serving layer using an appropriate paradigm, such as a **star schema**, **snowflake schema**, **data marts**, or an **one big table (OBT)** approach. Establish a domain-oriented semantic model—for e.g, through views containing unified metric definitions to ensure data projection consistency. Design the serving model around expected access and common query patterns, query performance, scalability, and cost efficiency, using techniques such as appropriate denormalization, partitioning, clustering, pre-aggregations, and materialized views.

4. **Orchestration:** Use of a data orchestrator (e.g., Airflow, Prefect, Dagster) to schedule and monitor your pipeline runs automatically.
5. **Containerization:** Containerize the relevant application components if needed using Docker to ensure consistent, reproducible execution.
6. **Data Quality/Testing:** Implementation of basic data quality checks (e.g., null checks, schema validation) and at least one unit test for your transformation logic.
7. **Serving Layer:** The processed data must be accessible to downstream users e.g., loaded into a Data Warehouse or platform, exposed via  BI tool/API etc.
8. **Error Handling & Resilience :** Pipelines must fail safely and restart cleanly. They should gracefully handle:
   * Ingestion and processing failures and timeouts
   * Malformed files and missing values
   * Duplicate records
   * Schema evolution handling

Additionally, your pipeline should include a backfilling mechanism to reprocess historical data seamlessly when needed.

9. **Logging & Monitoring:** Implementation and availability of structured logs capturing pipeline success/failure status and execution duration. Monitoring capabilities of the pipeline have importance.
10. **Data Compliance, Security & Governance:** Use only public, synthetic, or properly authorised data, and follow the source’s licence and terms of use. Your pipeline could incorporate:

    * Secure handling of credentials, API keys, and connection strings (e.g., using environment variables, Secrets Manager or GitHub Secrets etc) with strictly no hardcoded secrets in the codebase — do not commit them to Git via codebase, configurations or expose them in any logs **(Strongly recommended)**
    * For fully cloud-based and hybrid implementation, least-privilege access using Identity and Access Management (IAM) or Role-Based Access Control (RBAC) to restrict access to raw, processed, and served data layers accordingly. Pipeline services and users receive only the permissions required for their tasks.
    * If applicable - data masking, hashing, or any relevant method for Personally Identifiable Information (PII) or sensitive fields before they reach the serving layer. No sensitive data should be exposed in logs or codebase.
    * Basic data lineage and documentation to track data origins, transformations, dependencies and flow for the pipelines for end-to-end lineage from source to serving layer


### Progress Tracking
* **Full-day attendance:** Two daily check-ins (morning and afternoon)
* **1:1 Meetings:** Based on your project requirement and condition, the Instructor/TA may impose or schedule 1:1 Zoom meetings to provide targeted help.
* **Wednesday Weekly Meetings:** Every Wednesday during the capstone phase, you must attend the weekly project meeting. Be prepared to share:
  * What you have completed so far.
  * What you are currently working on.
  * What difficulties/blockers you are facing.
  * What specific help or guidance you need.



### Final Review
* **Final Pre-Submission Meeting:** Before the capstone project is officially submitted/presented, you must have a final meeting with the Instructor and TA. They will do a deep dive into your deliverables (code, pipeline execution, and documentation) to ensure everything meets the required minimum standards.

---

## Performance Evaluation Criteria

Your final grade and evaluation are continuously tracked by the TA and Instructor based on the following criteria:

1. **Process Adherence:** Did you follow the structured workflow (Business reqs -> Tech reqs -> Architecture -> Implementation) and consult with staff at each gate?
2. **Documentation Quality:** Evaluation of your `README.md`, `architecture.md`, `runbook.md`, and the maintenance of your ADRs.
3. **Technical Execution:** Does the project meet the minimum technical criteria? (Automated ingestion, transformation, orchestration, observability, pipeline idempotency, testing, serving, error handling, and logging etc).
4. **Communication & Engagement:** Active participation in the Wednesday weekly meetings, utilizing Instructor/TA support effectively and clarity in communicating blockers.
5. **Tracked Effort:** The TA will keep notes on your continuous effort throughout the project phases. Consistent progress shown in your Git commits and project management tool is heavily weighted; do not leave everything to the last minute.



### Appendix: Recommended Open Data Sources
Here are public data source links you may try to explore and use for your capstone project based on your requirement and feasibility:
| Dataset Name | Domain / Category | Description | Link |
| :--- | :--- | :--- | :--- |
| **GDELT Project** | Global News & Events | Monitors global news media in real-time, capturing events, actors, and sentiments across the world. | [gdeltproject.org](https://www.gdeltproject.org/) |
| **Registry of Open Data (AWS)** | Multi-domain Portal | A repository of public datasets hosted on Amazon Web Services (AWS) spanning genomics, climate, economics, and more. | [registry.opendata.aws](https://registry.opendata.aws/) |
| **Google Cloud Public Datasets** | Multi-domain Portal | A collection of public datasets available through Google BigQuery and Google Cloud Storage. | [cloud.google.com/datasets](https://cloud.google.com/datasets) |
| **Common Crawl** | Web Scraping / NLP | Raw web page HTML and metadata. Extremely unstructured, massive volume, requires heavy parsing, filtering, and distributed processing. | [commoncrawl.org](https://commoncrawl.org/) |
| **GitHub Archive** | Software Development | A chronological record of public GitHub events (commits, pull requests, issues) ideal for streaming/batch pipelines. | [gharchive.org](https://www.gharchive.org/) |
| **Stack Exchange Data Dump** | Q&A / Internet Forums | Anonymized dump of all user-contributed content on the Stack Exchange network (Stack Overflow, Server Fault, etc.). | [archive.org/details/stackexchange](https://archive.org/details/stackexchange) |
| **IMDb Datasets** | Entertainment | Subsets of IMDb data (movies, TV shows, cast, crew, ratings) updated daily. | [IMDb Interfaces](https://developer.imdb.com/non-commercial-datasets/) |
| **OpenStreetMap Planet** | Geospatial / Mapping | The entire OpenStreetMap database containing geographic and map data for the whole planet. | [planet.openstreetmap.org](https://planet.openstreetmap.org/) |
| **Open Food Facts** | Food & Beverage | A collaborative, free and open database of food products worldwide (ingredients, allergens, nutrition). | [world.openfoodfacts.org/data](https://world.openfoodfacts.org/data) |
| **US Bureau of Transportation Stats** | Transportation / Flights | US flight data including on-time performance, delays, cancellations, and flight schedules. | [transtats.bts.gov](https://transtats.bts.gov/) |
| **MIMIC-IV** | Healthcare | Deidentified health records of ICU patients at the Beth Israel Deaconess Medical Center. *(Requires credentialing)* | [physionet.org/content/mimiciv](https://physionet.org/content/mimiciv/) |
| **Amazon Reviews (UCSD)** | E-commerce / Reviews | A large dataset of product reviews from Amazon, including ratings, text, and product metadata. | [cseweb.ucsd.edu/~jmcauley](https://cseweb.ucsd.edu/~jmcauley/datasets.html) |
| **Wikipedia Pageviews** | Internet Traffic | Daily aggregated pageview counts for all Wikipedia articles across all languages. | [dumps.wikimedia.org](https://dumps.wikimedia.org/other/pageview_complete/) |
| **Steam Games Dataset (UCSD)** | Gaming / E-commerce | Data on Steam games including reviews, game metadata, pricing, and player statistics. | [cseweb.ucsd.edu/~jmcauley](https://cseweb.ucsd.edu/~jmcauley/datasets.html) |
| **NYC TLC Trip Record Data** | Transportation | Historical taxi/ride-share trips. Requires handling schema changes over the years, dirty data (bad GPS coordinates), and large aggregations. | [nyc.gov TLC Trip Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) |
| **FEC Campaign Finance Data** | Government / Politics | Itemized receipts and disbursements. Messy CSVs with inconsistent formatting, schema evolution over decades, and heavy relationships. | [fec.gov/data](https://www.fec.gov/data/) |
| **Citi Bike Trip Histories** | Transportation / Mobility | NYC bike share trips. Requires handling missing station IDs, streaming station status APIs, and time-series geospatial analytics. | [citibikenyc.com/system-data](https://citibikenyc.com/system-data) |

*Note: When using healthcare (e.g., MIMIC-IV) or proprietary-to-open-source datasets, ensure you comply with their specific data access agreements and terms of use.*

### Appendix: Technology Stacks

This reference lists commonly used tools and services that are relevant across the data engineering lifecycle, from design and ingestion to transformation, orchestration, quality, deployment, and observability. You may consider it to select a focused, appropriate stack for your project based on feasibility analysis and implementation needs.

| Tool | Description | Pipeline Phase |
| :--- | :--- | :--- |
| [Mermaid](https://mermaid.js.org/) | Diagrams‑as‑code library that turns text into flowcharts, sequence diagrams, ER diagrams, and simple architecture diagrams; integrates directly with Markdown/GitHub and works well for `architecture.md` and ADRs. | Planning & Architecture Design / Documentation |
| [Structurizr](https://structurizr.com/) | “Model‑as‑code” tooling for C4 diagrams (Context, Container, Component) with a DSL and browser UI, used to keep architecture diagrams version‑controlled and consistent. | Planning & Architecture Design |
| [Excalidraw](https://github.com/excalidraw/excalidraw) | Browser‑based, hand‑drawn style diagramming app, great for quick architecture and data‑flow sketches before formalizing designs. | Planning & Architecture Design |
| [Gamma](https://gamma.app/) | AI slide/deck builder with a free tier that turns notes or outlines into polished presentations and web‑style docs; useful for final capstone presentations and stakeholder demos. | Final Presentation / Documentation |
| [GitHub Projects](https://github.com/features/projects) | Kanban‑style project management directly tied to GitHub issues and pull requests; useful for tracking tasks, milestones, and blockers across the capstone. | Project Management (cross‑cutting) |
| [Marimo](https://marimo.io/) | Open‑source reactive Python notebook that stores notebooks as `.py` files, supports reproducible execution and interactive UIs, and can be executed as scripts or deployed as simple apps. | Exploration / Analysis / Notebook‑to‑App Prototyping |
| [Loguru](https://github.com/Delgan/loguru) | Ergonomic Python logging library offering structured logs, rotation, filters, and rich formatting with minimal setup; a common upgrade over the standard `logging` module for ETL services. | Development / Logging |
| [Terraform](https://www.terraform.io/) / [OpenTofu](https://opentofu.org/) | Infrastructure‑as‑Code tools for describing and provisioning cloud and data infrastructure. Terraform is the long‑standing standard; OpenTofu is the fully open‑source fork with very similar workflows and syntax. | Infrastructure / Environment Provisioning |
| [LocalStack](https://github.com/localstack/localstack) | Widely used AWS cloud emulator that runs services like S3, DynamoDB, SQS, SNS, and Lambda locally, enabling offline development and testing of AWS‑integrated data pipelines. | Dev Environment / Cloud Emulation |
| [MiniStack](https://ministack.org/) | MIT‑licensed AWS emulator exposing dozens of services (including S3, Lambda, RDS) via a single local endpoint; compatible with Terraform/CDK/Pulumi for cloud‑like tests without real AWS. | Dev Environment / Cloud Emulation |
| [Floci](https://floci.io/) | Lightweight local AWS/Azure/GCP emulator designed to start quickly and run without cloud credentials, enabling rapid multi‑cloud interaction tests on a laptop. | Dev Environment / Cloud Emulation |
| [Polars](https://pola.rs/) | High‑performance, Rust‑backed DataFrame library for Python with multi‑threaded, columnar execution; increasingly adopted when Pandas becomes a bottleneck on larger datasets. | Data Processing / Analysis |
| [MinIO](https://min.io/) | High‑performance, S3‑compatible object store; widely used as a local or on‑prem data lake layer for raw/curated files and ML artifacts, speaking the same API as AWS S3. | Storage (Data Lake / Artifacts) |
| [DuckDB](https://duckdb.org/) | Embeddable OLAP engine that runs in‑process and queries Parquet/CSV directly via SQL; common for local analytics and as a dbt‑core target in modern DE stacks. | Storage / Analytics / Transformation |
| [Redpanda](https://redpanda.com/) | Kafka‑API‑compatible streaming platform implemented as a single binary, optimized for low‑latency and containerized or single‑node deployments. | Streaming / Messaging |
| [Debezium](https://debezium.io/) | Open‑source CDC platform that captures row‑level changes from databases like Postgres/MySQL and publishes them to Kafka topics, powering real‑time pipelines. | Data Ingestion / Change Data Capture |
| [RisingWave](https://risingwave.com/open-source-streaming-database/) | Open‑source, Postgres‑compatible streaming database that continuously processes event streams via SQL to produce real‑time materialized views and analytics.| Streaming / Stream Processing / Serving |
| [Airbyte](https://github.com/airbytehq/airbyte) | Popular open‑source ELT platform with hundreds of connectors for SaaS, databases, and files; self‑hosted in many orgs to standardize ingestion. | Data Ingestion |
| [dbt‑core](https://github.com/dbt-labs/dbt-core) | SQL and Python based transformation framework with models, built-in tests, documentation, and data lineage; highly common in modern data warehouses and lakehouses. | Data Transformation / Semantic Modeling |
| [Prefect](https://www.prefect.io/) | Code‑first workflow orchestrator with Python APIs, flexible scheduling, and hybrid local/cloud deployment; widely adopted for data pipelines and ML flows. | Orchestration |
| [Dagster](https://dagster.io/) | Asset‑centric orchestrator emphasizing data assets, lineage, and testing; increasingly used in teams that want strong data‑first abstractions. | Orchestration |
| [Great Expectations](https://greatexpectations.io/) | Data quality and validation framework defining “expectations” about datasets, with profiling, tests, and auto‑generated data docs; a common choice for pipeline QA. | Data Quality & Testing |
| [Soda Core](https://github.com/sodadata/soda-core) | Open‑source CLI/Python engine for declarative data quality checks using SodaCL and YAML, integrated into pipelines and CI runs to enforce data contracts. | Data Quality & Testing |
| [SQLFluff](https://sqlfluff.com/) | Open-source SQL linter and formatter that enforces consistent, readable SQL and catches common syntax/style issues across dialects; integrates well with dbt projects and CI pipelines. | Data Transformation Quality / CI |
| [Chainguard Images](https://www.chainguard.dev/chainguard-images) | Secure, minimal, frequently rebuilt container base images designed to reduce software supply-chain risk and image attack surface. Use them as production base images for Python ingestion services, dbt runners, Airflow/Dagster jobs, Streamlit apps, and API services; note that some images/features require a commercial subscription. | Container Security / Build & Release |
| [Trivy](https://trivy.dev/) | Open-source security scanner for container images, filesystem dependencies, IaC, Kubernetes manifests, secrets, and SBOMs. Run it in CI before publishing an image to fail builds on high/critical vulnerabilities or accidentally committed secrets. | CI/CD Security / Vulnerability Scanning |
| [Metabase](https://www.metabase.com/start/oss/) | Open‑source BI tool providing GUI “questions” and dashboards on top of databases; very common for self‑service analytics in product and data teams. | Serving Layer / BI & Dashboards |
| [Apache Superset](https://superset.apache.org/) | Open‑source data exploration and visualization platform with SQL, charts, and interactive dashboards; widely used for analytics in OSS‑friendly stacks. | Serving Layer / BI & Dashboards |
| [Grafana](https://grafana.com/) | Visualization and dashboarding platform, especially strong for time‑series and operational metrics, commonly paired with Prometheus and Loki. | Serving Layer / Monitoring & Dashboards |
| [Streamlit](https://streamlit.io/) | Python framework for quickly turning scripts into interactive data apps and ML demos with sliders, charts, and forms; frequently used for internal tools and prototypes. | Serving Layer / Data Apps |
| [Prometheus](https://prometheus.io/) | Metrics database and scraping system used to monitor services, jobs, and infrastructure; standard choice for collecting pipeline and platform metrics. | Logging & Monitoring |
| [Loki](https://grafana.com/oss/loki/) | Log aggregation system in the Grafana ecosystem, storing logs in a compressed, indexable format for centralized search. | Logging & Monitoring |
| [HashiCorp Vault](https://www.vaultproject.io/) | Widely adopted secrets and identity management system for securely storing and controlling access to tokens, passwords, and certificates in production environments. | Security & Secrets Management |
| [Infisical](https://infisical.com/) | Open‑source (MIT‑licensed) secrets manager for synchronizing environment variables and secrets across services, CI pipelines, and local development. | Security & Secrets Management |
| [MLflow](https://mlflow.org/) | Industry‑standard open‑source ML lifecycle platform providing experiment tracking, model registry, and deployment tools; heavily used for MLOps across companies. | ML Training & Model Management |
| [Databricks Free Edition](https://www.databricks.com/learn/free-edition) | Free, quota and service limited Databricks workspace that lets you implement Lakehouse patterns, notebooks, SQL warehouses, and AI workflows on the same platform used in many enterprises. | Lakehouse Platform / Cloud Practice |