# taskpackage-git-sync test

Tests publishing Robocorp robots to Sema4.ai v3 task packages from GitHub Actions: merges to `main` publish to DEV, release tags publish to PROD after approval. See [`taskpackage-git-sync/README.md`](taskpackage-git-sync/README.md).

| Path | What |
| --- | --- |
| `robots/list-vault-secrets` | Demo robot (Vault, Asset Storage and run-context tests) |
| `taskpackage-git-sync/` | Sync script, folder-to-package mapping, docs and CI templates |
| `.github/workflows/taskpackage-git-sync.yml` | The workflow |
