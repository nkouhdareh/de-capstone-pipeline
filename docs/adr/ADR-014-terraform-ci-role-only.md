# ADR-014: Terraform scoped to the CI IAM role only

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-17 |
| **Deciders** | Nastaran Kouhdareh |

> *Recorded retrospectively. Implemented on 2026-08-17 as CI/CD phase 6 (PR #35).*

## Context

Infrastructure as code was listed in the technical requirements as **optional** and as
"the first item to cut". By 17 August the pipeline was complete, frozen, and running in
production, and the infrastructure it depended on had all been created by hand in the AWS
and Snowflake consoles: an S3 bucket, a Snowflake storage integration and its IAM role, an
uploader IAM user, a GitHub Actions OIDC role, and a permissions boundary.

The obvious ambition was to bring all of it under Terraform. The obvious risk was that
doing so, six days before the presentation, could destroy and recreate live infrastructure
that 45,030,932 rows of verified output depended on — for a documentation benefit.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Terraform manages exactly two objects: the GitHub Actions CI role and its inline policy, imported rather than created (chosen)** | A real, reviewed, drift-free IaC loop demonstrated end to end; zero risk to anything the pipeline depends on; small enough to verify completely | Most infrastructure remains click-ops; a reviewer may read the narrow scope as incompleteness unless the reasoning is stated |
| B — Terraform manages all AWS infrastructure | The complete story; a genuine rebuild-from-scratch capability | Importing a live S3 bucket, a storage integration and production IAM during a change freeze. A single `1 to change` on the wrong resource could break the Snowflake load path or the protected artifact. High risk, low marginal grade |
| C — Terraform for Snowflake objects too (via the Snowflake provider) | Users, roles and grants as code — where the drift risk actually is | A third provider to learn, and it would manage the identities the pipeline authenticates with. Worse risk profile than B during a freeze |
| D — No IaC; document the console steps | Zero risk | Fails an explicitly listed requirement, and produces no evidence of a plan/apply workflow |

## Decision

We chose **A**, and the scope is the decision:

> Terraform manages the **one** object created last, used only by CI, and depended on by
> nothing in the data path. Not the data bucket, not production IAM, not the Snowflake
> storage integration, not dbt, not Airflow.

The safety properties are as deliberate as the scope:

- **Imported, never created.** Declarative `import` blocks, so the takeover appears in the
  plan on the pull request. The acceptance gate is
  `Plan: 2 to import, 0 to add, 0 to change, 0 to destroy` — Terraform takes ownership
  **without changing a byte**.
- **`prevent_destroy = true`** on both resources.
- **The executor cannot delete what it manages.** `de-capstone-terraform` is an OIDC role,
  not an IAM user, with eleven IAM actions scoped to one role ARN and everything else
  denied. `iam:CreateRole` and `iam:DeleteRole` are explicitly denied. **Every `*` in its
  policy sits inside a `Deny`.** Verified in the IAM policy simulator: it can update that
  role, **cannot delete it, cannot attach a managed policy to it, and cannot write policy
  onto itself.**
- **`apply` is manual** (`workflow_dispatch`), not on merge. The first apply is one to
  watch.
- **State** lives in a dedicated private, versioned, SSE-S3 bucket with `use_lockfile =
  true` (no DynamoDB table), bootstrapped by hand — a backend must exist before
  `terraform init` can run.

**The acceptance test is the empty second plan.** Results from PR #35:

```
plan   →  2 to import, 0 to add, 0 to change, 0 to destroy
apply  →  2 imported, 0 added, 0 changed, 0 destroyed
plan   →  No changes. Your infrastructure matches the configuration.
```

An apply reporting success proves Terraform did *something*. **An empty plan afterwards
proves it recorded reality faithfully, with no hidden drift.** That third line is the one
that matters.

## Consequences

**Positive:** A complete IaC loop — plan on PR, reviewed diff, manual apply, verified
no-drift — demonstrated on real infrastructure with zero risk to the pipeline. The S3
contract check was re-run afterwards and stayed green at 486 objects / 3,913,635,942
bytes, confirming nothing moved.

**One failure worth keeping.** The first plan died on
`AccessDenied: iam:ListOpenIDConnectProviders`. A `data` block was looking the OIDC
provider up **by URL**, and resolving a URL to an ARN requires that action — which AWS does
not support resource-level permissions for, so granting it would have meant
`"Resource": "*"` inside an `Allow`. The reflex is to widen the policy. **The right fix was
to remove the dependency**: reference the provider ARN as a literal in a `locals` block and
delete the data source. The string is identical, so the imported trust policy still matched
and the plan stayed `0 to change`. *The least-privilege policy caught an over-broad
dependency in my own code.*

**Negative / accepted trade-offs:**

- The S3 bucket, the storage integration, the uploader user and every Snowflake object
  remain click-ops. The project **cannot** be rebuilt from scratch by `terraform apply`.
- Two objects under management and a dozen outside it is a split that must be explained
  rather than being self-evident.
- Known open items, deliberately left during the freeze: delete the spent `imports.tf`
  now the import has run; tighten the CI role's trust policy from `StringLike "…:*"` to the
  two exact subjects **through Terraform, as a reviewed plan diff**; drop the now-unused
  `iam:GetOpenIDConnectProvider`.

**Revisit if:** the project needs to be reproducible in another AWS account, or a second
person needs to change infrastructure. Both are the point at which importing the remaining
resources stops being risk for its own sake and starts buying something.
