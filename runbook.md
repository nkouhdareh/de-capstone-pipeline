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

### Manual trigger — download drug/label and drug/ndc (bulk files)

**What the scripts do** (`scripts/ingest_drug_label.py`, `scripts/ingest_drug_ndc.py`):

- Both datasets are past the API's 26,000 paging limit, so they use openFDA's **bulk download files** (no API key needed).
- Each `.json.zip` is downloaded and its records saved as **raw** NDJSON in the bronze layer.

**Run them** (virtual environment activated):

```bash
python scripts/ingest_drug_ndc.py
```

```bash
python scripts/ingest_drug_label.py
```

**Where the data is saved:**

```
D:/capstone/data/bronze/drug_ndc/part-<n>.json
D:/capstone/data/bronze/drug_label/part-<n>.json
```

**Note:** label is large (261k full label texts, several GB). For a quick sample, set `MAX_FILES = 1` near the top of `ingest_drug_label.py`.

### Backfill / re-fetch specific days

If a day comes up short (a page failed mid-download), re-fetch just those days with
`scripts/backfill_days.py` (edit the `DAYS` list at the top; uses your API key):

```bash
python scripts/backfill_days.py
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

### Ingested so far (verified)

Each count was checked against openFDA's own totals.

| Dataset | Records | How verified |
|---|---|---|
| `drug_event` (2023–2024) | **2,687,675** | matches openFDA range total exactly |
| `drug_label` | **261,258** | matches the bulk-file record count |
| `drug_ndc` | **136,520** | matches the bulk-file record count |

**Count records on disk for any dataset:**

```bash
find /d/capstone/data/bronze/<dataset> -name "*.json" -exec cat {} + | wc -l
```

### Explore the data (Spark + Jupyter)

Exploration and the data-quality checks run in **PySpark inside Jupyter**, via Docker
(`docker-compose.yml`, reusing the week-12 setup). Everything runs **locally** on this
laptop — nothing is in the cloud.

```bash
docker compose up
```

Then open **http://localhost:8888** → `work/01_explore_drug_event.ipynb` → **Run All Cells**.
First run pulls the image (~2–4 min). On Windows, share the **D:** drive in Docker Desktop →
Settings → Resources → File Sharing.

**Why Spark, not pandas, to explore this data?**

The bronze `drug_event` data is **~2.69M nested JSON records** (a few GB). On a 16 GB laptop:

- **pandas** loads the whole dataset into RAM at once. At this size it does not fit in 16 GB,
  so it runs out of memory and crashes — pandas is all-in-memory or nothing.
- **Spark** processes the data in small **chunks (partitions)**, a few at a time, and **spills
  the overflow to disk** when memory is tight. It only needs RAM for the chunk it is working on,
  never the whole dataset — so it can handle data **bigger than memory**. It also spreads the
  work across all CPU **cores**, so it is faster too.

The point is **not** that "Spark is faster" — on a small sample pandas is actually faster (no
startup overhead). The point is that **Spark scales to data bigger than memory**: it can process
the full 2.69M-record dataset on one 16 GB machine, which pandas cannot. pandas stays useful for
a quick look at a small sample; Spark is the tool for the full dataset (and the Silver-layer
cleaning).

*On one laptop Spark parallelises across CPU **cores**, not **nodes** — nodes are separate
machines in a cloud cluster, the same idea at bigger scale. The overall Spark decision is
recorded in `docs/adr/ADR-004`.*

**Speed: cache the raw JSON as Parquet**

Reading the raw **nested JSON** repeatedly is slow — every Spark check re-reads and re-parses
all 3,043 files (one completeness cell took **over an hour**). Cache it once as **Parquet**
(binary, schema stored, columnar, compressed), then read that instead:

```python
df.write.mode('overwrite').parquet('/home/jovyan/dq_cache/drug_event')   # one-time, slow
df = spark.read.parquet('/home/jovyan/dq_cache/drug_event')              # fast from here on
```

Reads then drop from **minutes to seconds**. This cache lives inside the container (temporary —
rebuild with the write line if you `docker compose down`); the permanent Parquet lands in the
Silver layer. Pattern: **JSON to land, Parquet to work**.

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

### Data quality baseline — bronze `drug_event` (from exploration)

Known-good numbers from exploring the 2,687,675-record bronze. Use these to tell a **real problem
from a normal, expected gap**. Full detail: `notebooks/01_explore_drug_event.ipynb`.

| Check | Expected / healthy | Note |
|---|---|---|
| Duplicate `safetyreportid` | **0** | openFDA returns latest-version only |
| Key fields null (`safetyreportid`, `receivedate`, `serious`) | ~0% | `serious` ~0.01% |
| Drug name & reaction present | **100%** | `medicinalproduct`, `reactionmeddrapt` never null/blank |
| Demographics missing | age ~44%, sex ~17%, country ~11% | **expected** — bucket as `Unknown`, not a bug |
| Drug-name resolution (`openfda.generic_name`) | ~83% present | Tier-1 source for #5 normalisation |
| Fan-out per report | ~3.9 drugs, ~3.0 reactions | 10.4M drug rows, 8.0M reaction rows |

---

## 4. Failure playbook

*One row per failure you actually encounter. This section is the real deliverable.*

| Symptom | Likely cause | Fix | Safe to re-run? |
|---|---|---|---|
| Task fails with HTTP 429 | Rate limit exceeded | Wait; backoff handles it automatically | Yes |
| `venv` ends in `KeyboardInterrupt`, venv half-made | Ctrl+C pressed during setup | `rm -rf .venv`, then `python -m venv .venv` and let it finish | Yes |
| `bash: ...activate: command not found` | Backslashes used in Git Bash | Use `source .venv/Scripts/activate` (forward slashes) | Yes |
| Fewer records on disk than openFDA's count | A page request failed and the old script treated the empty reply as "day finished" | Compare per-day API count vs disk, re-fetch the short day(s); script now **raises** on a failed page instead of skipping | Yes |
| `SSL: CERTIFICATE_VERIFY_FAILED` on a bulk download | `urllib` couldn't verify the certificate (Windows / antivirus scanning HTTPS) | Use `requests` (it ships the certifi CA bundle) — the label/ndc scripts now do | Yes |
| HTTP 403 on the API | Keyless request hit the low rate limit | Use your API key (`OPENFDA_API_KEY` in `.env`) | Yes |
| A Spark cell takes ~1 hour | Re-reading + re-parsing nested JSON on every check (no cache) | Cache once to Parquet (`df.write.parquet(...)`), then read the Parquet — seconds, not minutes | Yes |

---

## 5. Recovery procedures

### A run failed partway through

**Ingestion has no auto-checkpoint yet** — it restarts from `START`. To resume an interrupted
`ingest_drug_event.py`:

1. Note the **last `receivedate=` folder** written (e.g. `20241018`).
2. **Delete that day's folder** — it may be half-written: `rm -rf .../drug_event/receivedate=20241018`.
3. Set `START` in the script to that date, save, and re-run — it fills only the remaining days.
4. Afterwards, set `START` back to the full range.

For **specific short days** (a page failed mid-day), use `scripts/backfill_days.py` instead
(edit its `DAYS` list) — it re-fetches just those days with your key. Verify with per-day
API count vs disk.

### Data looks wrong in the marts

*How to trace back through the layers to find where it broke.*

### Rebuilding from raw

*Bronze is immutable, so silver and gold can be rebuilt without re-ingesting.*

---

## 6. Teardown

```bash
docker compose down -v
```

- **`docker compose stop`** — pauses the container and **keeps** the Parquet cache. Use this between sessions.
- **`docker compose down`** — removes the container; the **Parquet cache is lost** (rebuild it with the write cell). `-v` additionally removes named volumes.
- **Your data and notebooks are never deleted** by any of these — they live in host folders (bind mounts), not inside Docker.

*Cloud-side to destroy to avoid cost: none yet (everything is local so far).*
