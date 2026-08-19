# ADR-012: Key-pair authentication with a `TYPE = SERVICE` identity

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-13 |
| **Deciders** | Nastaran Kouhdareh |

> *Recorded retrospectively. The migration was performed on 2026-08-13, ahead of
> Snowflake's 2026-08-18 deadline.*

## Context

Two things converged.

**A hard deadline.** Snowflake deprecated **password-only sign-ins on 18 August 2026** —
six days before the capstone presentation. Four of the eight DAG tasks (`load_raw`,
`dbt_build`, `dbt_test`, `publish_metrics`) authenticate to Snowflake, plus both loaders
and every dashboard. All of them would have broken.

**A pre-existing weakness.** The pipeline was authenticating as `NKOUH` — a human account
whose default role was `ACCOUNTADMIN`. Every automated task therefore ran with
account-administrator rights, and the same credential was used for interactive UI work and
for unattended jobs. Rotating it, revoking it, or auditing which of the two had done
something were all impossible to do cleanly.

The deadline forced a change that should have happened anyway, so it was used to fix both
problems at once rather than only the urgent one.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — A dedicated `TYPE = SERVICE` user with key-pair auth, limited to `DE_CAPSTONE_DBT_ROLE` (chosen)** | Survives the deprecation; separates human from machine identity; **a `TYPE = SERVICE` user cannot have a password at all**, so the strongest claim becomes structurally true rather than merely observed; the key lives outside the repository | A key pair to generate, register, mount and eventually rotate; one more identity |
| B — Keep `NKOUH`, add a key pair to it | Smallest change; meets the deadline | Human and machine identity stay fused; automated tasks keep `ACCOUNTADMIN` by default; a password still exists on the account, so "there is no Snowflake password" would be false |
| C — Password + MFA everywhere | Familiar | **Impossible after 18 August**, and MFA cannot work unattended in a DAG |
| D | OAuth / external browser SSO | Good for humans | Requires interaction; unusable for scheduled jobs |

## Decision

We chose **A**, splitting the identities:

| Identity | Purpose | Authentication |
|---|---|---|
| `NKOUH` | Snowsight UI, administration | password + TOTP MFA |
| **`DE_CAPSTONE_SVC`** | dbt, Airflow, both loaders, the dashboards | **key-pair only** — `TYPE = SERVICE` users cannot hold a password |

A 2048-bit RSA key pair in PKCS#8, generated **outside the repository** and stored at
`D:/capstone/.keys/`, mounted read-only into the dbt container. `profiles.yml` reads
`SNOWFLAKE_PRIVATE_KEY_PATH` from the environment, so one profile serves both the
container (`/keys/rsa_key.p8`) and the host `.venv-dbt` — the same file, two paths, no
duplicated configuration.

The service identity is limited to `DE_CAPSTONE_DBT_ROLE`, not `ACCOUNTADMIN`.

**Both loaders were migrated, including the rollback path** (`scripts/load_to_snowflake.py`).
A rollback is only worth claiming if it still runs.

The blast radius was already small by earlier accident: because `load_raw` runs as a dbt
macro in the dbt container rather than through `snowflake.connector` in the Airflow worker
([ADR-010](ADR-010-airflow-triggers-containers.md)), **the Snowflake credential existed in
exactly one place** before this change and still does.

## Consequences

**Positive:** **There is no Snowflake password anywhere in this project**, and that is not
a policy — it is a property of the user type. The claim is verified on every commit by the
`secret scan` job in `ci.yml`, which was demonstrated turning red in 7 seconds on a
planted `SNOWFLAKE_PASSWORD`, printing file and line and never the value. The pipeline no
longer runs as `ACCOUNTADMIN`. Human and machine actions are separable in the query
history. Verified after migration: `dbt debug` passing in-container and on the host, the
rollback loader connecting as
`('DE_CAPSTONE_SVC', 'DE_CAPSTONE_DBT_ROLE', 'DE_CAPSTONE_WH')`, and a full eight-task DAG
run green in 14 m 36 s.

**Negative / accepted trade-offs:**

- A private key must be distributed to every environment that needs it, and there is no
  secret manager in this project — the key is a file on disk, protected by being outside
  version control and by `*.p8` being git-ignored.
- Key rotation is manual: regenerate, `ALTER USER … SET RSA_PUBLIC_KEY`, redistribute.
- Key-pair failures are opaque. Three distinct errors (`Could not deserialize key data`,
  `JWT token is invalid`, `No such file or directory: /keys/rsa_key.p8`) mean three
  different things — wrong key format, wrong registered key or wrong user, and a mount
  that was never applied. All three are now runbook entries, including that
  `docker compose up -d --force-recreate dbt` is required because a plain restart does not
  add a new mount.
- `NKOUH` is the only human user and the only `ACCOUNTADMIN`, with a single MFA method. A
  lost phone means contacting Snowflake support. A second MFA factor is a known open item.

**Revisit if:** the project gains more than one operator, or moves anywhere with a secret
manager available — at which point the key belongs in AWS Secrets Manager or Vault rather
than on a disk, and rotation can be automated.
