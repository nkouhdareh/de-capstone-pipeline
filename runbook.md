# Runbook

Operational manual: how to run this, and what to do when it breaks.

> Fill this in **as you hit each problem**, not at the end. Every failure you debug
> during the build is a runbook entry you have already earned.

---

## 1. Environment

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11 |
| Disk space | ~25 GB free for raw data (stored on the D: drive) |
| Docker Desktop | Needed later for Airflow, not for ingestion |

### First-time setup (data ingestion)

Run these **once**, from inside the `de-capstone` folder in Git Bash:

```bash
python -m venv .venv
```

```bash
source .venv/Scripts/activate
```

```bash
pip install requests python-dotenv
```

After activating, you will see `(.venv)` at the start of the terminal line.

Then create a file named `.env` inside `de-capstone` with:

```
OPENFDA_API_KEY=your_key_here
DATA_DIR=D:/capstone/data
```

*(Docker / Airflow setup comes later, when we orchestrate the pipeline.)*

### Required environment variables

| Variable | Purpose | Where to get it |
|---|---|---|
| `OPENFDA_API_KEY` | Raises the API limit to 120,000 requests/day | Free from open.fda.gov (emailed to you) |
| `DATA_DIR` | Where raw data is saved (never in the repo) | Your own path, e.g. `D:/capstone/data` |

---

## 2. Running the pipeline

### Normal scheduled run

```bash
# schedule, entry point, expected duration
```

### Manual trigger — download raw drug/event data

**What the script does** (`scripts/ingest_drug_event.py`):

- Downloads drug adverse-event reports (FAERS) from the openFDA API.
- Goes **day by day** and pulls **1,000 records per request**, so it never hits openFDA's 26,000-per-query limit.
- Saves the **raw** JSON to the bronze layer — one folder per date, one record per line.
- Stops at `TARGET` records (3,000,000) or the `END` date. For 2023–2024 that is about **2.69 million** records.

**Run it** (virtual environment activated):

```bash
python scripts/ingest_drug_event.py
```

**Where the data is saved:**

```
D:/capstone/data/bronze/drug_event/receivedate=YYYYMMDD/part-<n>.json
```

**To change what you pull:** edit `START`, `END`, or `TARGET` near the top of the script.

### Backfill a historical period

```bash
```

### Verifying a run succeeded

While running, the script prints one line per 1,000 records, for example:

```
20230101  skip=0  got=1000  total=1,000
20230101  skip=1000  got=1000  total=2,000
```

- `total` climbs toward ~2,687,675 for 2023–2024.
- It ends with `DONE. 2,687,675 records saved to ...`.
- Healthy runtime: roughly 30–60 minutes.
- Check that `D:/capstone/data/bronze/drug_event/` contains `receivedate=...` folders with `.json` files inside.

---

## 3. Monitoring

| What | Where to look | Healthy range |
|---|---|---|
| Run status | | |
| Rows ingested | | |
| Duplicates removed | | |
| Rejected rows | | |
| Runtime | | |
| Cost per run | | |

---

## 4. Failure playbook

*One row per failure you actually encounter. This section is the real deliverable.*

| Symptom | Likely cause | Fix | Safe to re-run? |
|---|---|---|---|
| Task fails with HTTP 429 | Rate limit exceeded | Wait; backoff handles it automatically | Yes |
| `venv` ends in `KeyboardInterrupt`, venv half-made | Ctrl+C pressed during setup | `rm -rf .venv`, then `python -m venv .venv` and let it finish | Yes |
| `bash: ...activate: command not found` | Backslashes used in Git Bash | Use `source .venv/Scripts/activate` (forward slashes) | Yes |

---

## 5. Recovery procedures

### A run failed partway through

*Is it safe to simply re-run? What does the checkpoint do?*

### Data looks wrong in the marts

*How to trace back through the layers to find where it broke.*

### Rebuilding from raw

*Bronze is immutable, so silver and gold can be rebuilt without re-ingesting.*

---

## 6. Teardown

```bash
docker compose down -v
```

*Anything cloud-side that must be destroyed to avoid cost.*
