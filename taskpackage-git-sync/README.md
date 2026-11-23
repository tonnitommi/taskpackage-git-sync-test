# Task package git sync

Publish Robocorp robots from a Git repository to Sema4.ai v3 task packages from GitHub Actions or GitLab CI: every merge to the main branch goes to DEV, and a release tag goes to PROD after approval.

Control Room had built-in GitHub and GitLab integrations. In v3, CI publishes with `rcc cloud push` instead: v3 speaks the same rcc cloud API Control Room did. Each push adds a new version to a task package, and workflows always run a package's latest version, so nothing else needs changing.

This repository tests the setup end to end before it moves to [`sema4ai-external/robocorp-to-v3`](https://github.com/sema4ai-external/robocorp-to-v3) once it works. Tracking: [EPD-10883](https://linear.app/sema4ai/issue/EPD-10883).

## The blueprint: DEV on merge, PROD on release tag

| Git event | Publishes to | Gate |
| --- | --- | --- |
| Merge to the main branch | DEV packages, for each robot folder that changed | Protected branch, reviewed pull request |
| Tag `<release>/v1.2.0`, for example `list-vault-secrets/v1.2.0` | PROD package of that one robot | Protected tags, and approval in the `v3-prod` environment |
| Tag `v1.2.0` | PROD packages of every robot | Same |

This is trunk-based development with promotion by tag, the pattern most enterprises already use to deploy applications:

* **PROD runs exactly what was tested in DEV.** A tag points at a commit that has been on the main branch, and so in DEV, since it merged.
* **"What's in PROD?" has a one-word answer:** the latest release tag. Tags are immutable, and every PROD version maps to one.
* **Approval and secrets come from the CI platform.** The PROD credential lives in the `v3-prod` environment, which only release-tag jobs can use, and only after a reviewer approves. DEV jobs can't reach it.
* **Rollback is a re-run:** run the release job on the previous tag.
* **One repository can hold many robots.** Per-robot tags release one robot without touching the others.

We don't recommend long-lived environment branches (a `dev` branch beside `main`). Promotion then means merging between branches, which drift apart through hotfixes and merges in both directions. PROD ends up running a merge result that never ran in DEV.

### Where DEV packages live

The mapping file supports both setups; only the ids differ.

| Setup | How | When to choose it |
| --- | --- | --- |
| **Separate DEV and PROD workspaces** (recommended for production use) | Each environment names its own workspace. Package, Vault secret and asset names can be the same in both; the robot reads whichever workspace it runs in. Each workspace has its own workers and its own credential. | Production processes, real credentials, separate DEV and PROD workers. Matches how most Control Room customers split their environments. |
| **Package pairs in one workspace** | Both environments name the same workspace; each robot has two packages, such as `relink-tests-dev` and `relink-tests`. | Small teams and trials. DEV and PROD runs share secrets, assets and workers. |

## Files

| File | What it is |
| --- | --- |
| `v3-packages.yaml` | The environments, and for each robot folder its package id in each environment. |
| `taskpackage_sync.py` | Picks the folders to publish (changed since the last push, or named by a release tag) and runs `rcc cloud push` for each. Downloads rcc and the instance's rcc profile itself. Python standard library only. |
| `github-actions.yml` | GitHub Actions template. This repository's live copy is `.github/workflows/taskpackage-git-sync.yml`. |
| `gitlab-ci.yml` | GitLab CI template. Not tested yet. |

## The mapping file

```yaml
environments:
  dev:
    workspace: <dev workspace id>
  prod:
    workspace: <prod workspace id>      # the same id as dev, for package pairs
    # url: https://other.instance        # only when PROD is on another v3 instance than V3_URL

packages:
  robots/invoice-bot:                    # folder holding robot.yaml
    release: invoice-bot                 # tag prefix; defaults to the folder name
    dev: <package id>
    prod: <package id>
  robots/experimental-bot:
    dev: <package id>                    # no prod id: never released to PROD
```

* The workspace id is the "Account ID" in v3 under a package's Publish → Publish with rcc.
* Package ids are not secret, and they stay the same when a package is renamed in v3.
* Changing this file publishes every mapped folder to DEV, so a newly added robot is published at once.

## Setup

1. **Create the packages in v3**, one per robot and environment: upload a first version, or use `rcc cloud new`. Copy each package's id into `v3-packages.yaml`.
2. **Create an rcc access credential** for each workspace CI publishes to, in v3 under your account menu → Access credentials (`/account/access-credentials`). Copy the `identifier:secret` value; it is shown once.
3. **Set up the CI environments.**
   * GitHub: Settings → Environments → create `v3-dev` and `v3-prod`. On `v3-prod`, add required reviewers and limit deployments to tags matching `*/v*` and `v*`. Under Settings → Rules, protect those tag patterns so only release managers can create them.
   * GitLab: protect the tags `*/v*` and `v*`, and protect the `v3-prod` environment with required approvals.
4. **Store the settings.**
   * `V3_RCC_CREDENTIALS` (secret) and `V3_URL` (variable, for example `https://us3.sema4.ai`).
   * Separate workspaces: set the secret on each environment, with that workspace's credential.
   * Package pairs: one repository-level secret is enough.
5. **Copy the template** for your CI and adjust its branch, paths and `SYNC_DIR`.

## Releasing to PROD

```bash
git tag list-vault-secrets/v1.0.0 <commit on main>
git push origin list-vault-secrets/v1.0.0
```

The PROD job waits for approval in `v3-prod`, then publishes that commit to the robot's PROD package. To roll back, re-run the job of the previous tag. You can also start it from the Actions tab with "Run workflow", choosing the tag.

To see what would be published without contacting v3:

```bash
./taskpackage_sync.py --environment dev --base <commit> --dry-run
./taskpackage_sync.py --environment prod --tag list-vault-secrets/v1.0.0 --dry-run
```

## The credential is personal, for now

An rcc access credential belongs to the person who created it. It publishes with that person's access, in every workspace where they can publish, and it stops working when they lose that access. Until v3 has workspace-scoped API keys ([EPD-10896](https://linear.app/sema4ai/issue/EPD-10896)) that rcc accepts ([EPD-10899](https://linear.app/sema4ai/issue/EPD-10899)):

* Use the credential of a person, or a dedicated CI user, who belongs only to the workspaces CI publishes to.
* Name the credential after the repository and environment, so it is easy to find and revoke.

Once workspace keys work with rcc, only the `V3_RCC_CREDENTIALS` values change.

v3 does not yet record which commit a version was published from ([EPD-10899](https://linear.app/sema4ai/issue/EPD-10899)). Until it does, the CI run log and the release tag are the record.

## Alternative: Publish from GitHub

v3 can also link a package to a GitHub repository, branch and folder (package → Publish → Publish from GitHub). Each version is then published by pressing Publish in v3; it does not publish on push. A linked package refuses `rcc cloud push`, so choose one method per package.
