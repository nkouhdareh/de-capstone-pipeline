# Runbook

Operational manual: how to run this, and what to do when it breaks.

> Fill this in **as you hit each problem**, not at the end. Every failure you debug
> during the build is a runbook entry you have already earned.

---

## 1. Environment

### Prerequisites

| Requirement | Version |
|---|---|
| Docker Desktop | |
| Python | 3.11 |
| Disk space | |

### First-time setup

```bash
cp .env.example .env
# fill in: API key, warehouse credentials
docker compose up -d
```

### Required environment variables

| Variable | Purpose | Where to get it |
|---|---|---|
| | | |

---

## 2. Running the pipeline

### Normal scheduled run

```bash
# schedule, entry point, expected duration
```

### Manual trigger

```bash
```

### Backfill a historical period

```bash
```

### Verifying a run succeeded

*What to check, and what "healthy" looks like — row counts, duration, test results.*

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
| | | | |

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
