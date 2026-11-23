import os
import re
from datetime import datetime, timezone
from pathlib import Path

from robocorp import storage, vault
from robocorp.tasks import get_output_dir, task
from RPA.Robocorp.Storage import Storage
from RPA.Robocorp.Vault import Vault

SECRET_NAME = "salaisuus"


@task
def print_secret():
    """Read one secret from the Control Room vault and print its keys and values."""
    secret = vault.get_secret(SECRET_NAME)
    print(f"Secret '{SECRET_NAME}':")
    for key, value in secret.items():
        print(f"  {key} = {value}")


@task
def get_all_assets():
    """List every Control Room asset and download each one to output/assets."""
    out_dir = Path(get_output_dir() or "output") / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    names = storage.list_assets()
    print(f"Found {len(names)} asset(s)")
    for name in names:
        safe_name = re.sub(r"[^\w.\-]", "_", name)
        path = storage.get_file(name, out_dir / safe_name, exist_ok=True)
        print(f"\n=== {name} -> {path} ({path.stat().st_size} bytes) ===")
        try:
            print(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            print("<binary content, not printed>")


KNOWN_RUN_VARS = [
    "RC_WORKSPACE_ID",
    "RC_PROCESS_ID",
    "RC_PROCESS_NAME",
    "RC_PROCESS_RUN_ID",
    "RC_PROCESS_RUN_NUMBER",
    "RC_ACTIVITY_ID",
    "RC_ACTIVITY_NAME",
    "RC_ACTIVITY_RUN_ID",
    "RC_ACTIVITY_RUN_NUMBER",
    "RC_ELEMENT_ID",
    "RC_ENVIRONMENT_NAME",
]
SENSITIVE_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "KEY")


@task
def print_run_details():
    """Print the Control Room run context (workspace, process, run ids, ...) from env vars."""
    print("Run details:")
    for name in KNOWN_RUN_VARS:
        print(f"  {name} = {os.environ.get(name, '<not set>')}")

    others = sorted(
        k for k in os.environ
        if k.startswith(("RC_", "ROBOCORP_")) and k not in KNOWN_RUN_VARS
    )
    if others:
        print("\nOther RC_/ROBOCORP_ variables:")
        for name in others:
            value = os.environ[name]
            if any(m in name.upper() for m in SENSITIVE_MARKERS):
                value = "<redacted>"
            print(f"  {name} = {value}")


WRITE_ASSET_NAME = "relink_write_test"
WRITE_SECRET_KEY = "relink_write_test"


def _write_marker() -> str:
    run_id = os.environ.get("RC_PROCESS_RUN_ID", "<no run id>")
    return f"written {datetime.now(timezone.utc).isoformat()} by run {run_id}"


@task
def write_asset():
    """Write a text asset with RPA.Robocorp.Storage, read it back and check that it matches."""
    lib = Storage()
    marker = _write_marker()
    lib.set_text_asset(WRITE_ASSET_NAME, marker)
    print(f"Wrote asset '{WRITE_ASSET_NAME}': {marker}")

    read_back = lib.get_text_asset(WRITE_ASSET_NAME)
    print(f"Read back: {read_back}")
    if read_back != marker:
        raise AssertionError("Asset read back does not match what was written")
    print("Asset write OK")


@task
def delete_asset():
    """Delete the asset Write Asset made with RPA.Robocorp.Storage and check it is gone."""
    lib = Storage()
    lib.delete_asset(WRITE_ASSET_NAME)
    print(f"Deleted asset '{WRITE_ASSET_NAME}'")

    names = lib.list_assets()
    print(f"Assets after delete: {names}")
    if WRITE_ASSET_NAME in names:
        raise AssertionError("Asset is still listed after delete")
    print("Asset delete OK")


@task
def write_secret():
    """Set one key in the vault secret with RPA.Robocorp.Vault, read it again and check it.

    The other keys are kept as they are and their values are not printed.
    """
    lib = Vault()
    marker = _write_marker()
    secret = lib.get_secret(SECRET_NAME)
    secret[WRITE_SECRET_KEY] = marker
    lib.set_secret(secret)
    print(f"Set '{SECRET_NAME}'.{WRITE_SECRET_KEY} = {marker}")

    read_back = lib.get_secret(SECRET_NAME)
    print(f"Keys after write: {sorted(read_back.keys())}")
    print(f"Read back: {read_back.get(WRITE_SECRET_KEY)}")
    if read_back.get(WRITE_SECRET_KEY) != marker:
        raise AssertionError("Secret read back does not match what was written")
    print("Secret write OK")
