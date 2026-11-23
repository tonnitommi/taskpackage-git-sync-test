# Publish to v3: test repository


The DEV and PROD setup from [Publish robots from Git to v3](https://github.com/sema4ai-external/robocorp-to-v3/tree/main/publish-from-git), running for real. Merges to `main` publish to DEV, and release tags publish to PROD after approval.

| Path | What |
| --- | --- |
| `robots/list-vault-secrets` | Demo robot (Vault, Asset Storage and run-context tests) |
| `v3-publish/` | The sync script and the folder-to-package mapping |
| `.github/workflows/publish-to-v3.yml` | The workflow |
