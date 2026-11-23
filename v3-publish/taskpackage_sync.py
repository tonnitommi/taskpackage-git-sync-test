#!/usr/bin/env python3
"""Publish robot folders to Sema4.ai v3 task packages with `rcc cloud push`.

Reads v3-packages.yaml (environments, and per robot folder a package id per environment) and
publishes to one environment. --environment may be left out when the file names only one.

  Push: taskpackage_sync.py [--environment dev] --base <commit>
        Publishes each mapped folder that changed between <commit> and HEAD. Publishes every
        mapped folder when <commit> is missing or unknown, or when the mapping file changed.
  Tag:  taskpackage_sync.py --environment prod --tag <tag>
        "<release>/v1.2.0" publishes the folder whose release name matches; "v1.2.0" publishes
        every folder that has a PROD package.
  Any:  --all publishes every folder mapped for the environment; --dry-run only prints.

Environment variables: V3_RCC_CREDENTIALS (rcc access credential, identifier:secret), V3_URL
(instance, unless the environment names its own url), RCC_VERSION (default v19.0.1).
Standard library only, so it runs on stock CI images.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MAPPING = SCRIPT_DIR / "v3-packages.yaml"
DEFAULT_RCC_VERSION = "v19.0.1"
RCC_DOWNLOAD = "https://cdn.sema4.ai/rcc/releases/{version}/linux64/rcc"
MANIFESTS = ("robot.yaml", "package.yaml")


class SyncError(Exception):
    """A problem the person running the sync can fix."""


@dataclass(frozen=True)
class Target:
    folder: str
    package_id: str
    release: str


# --- Mapping ------------------------------------------------------------------------------------


def parse_nested_yaml(text: str) -> dict:
    """Parse the mapping file's YAML subset: nested `key: value` maps, comments, quoted scalars."""
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for number, raw in enumerate(text.splitlines(), start=1):
        line = re.sub(r"\s+#.*$", "", raw).rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, sep, value = line.strip().partition(":")
        if not sep or not key:
            raise SyncError(f"line {number}: expected 'key: value', got {raw.strip()!r}")
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        key = key.strip().strip("\"'")
        value = value.strip().strip("\"'")
        if value:
            parent[key] = value
        else:
            parent[key] = {}
            stack.append((indent, parent[key]))
    return root


def load_mapping(path: Path) -> dict:
    if not path.is_file():
        raise SyncError(f"mapping file not found: {path}")
    mapping = parse_nested_yaml(path.read_text())
    if not isinstance(mapping.get("environments"), dict) or not mapping["environments"]:
        raise SyncError(f"{path.name}: 'environments:' is missing or empty")
    if not isinstance(mapping.get("packages"), dict) or not mapping["packages"]:
        raise SyncError(f"{path.name}: 'packages:' is missing or empty")
    return mapping


def targets_for(mapping: dict, environment: str, repo_root: Path) -> list[Target]:
    """Every folder with a package id for this environment."""
    targets = []
    for folder, entry in mapping["packages"].items():
        if not isinstance(entry, dict):
            raise SyncError(f"packages.{folder}: expected environment keys (dev, prod, ...), got a single value")
        package_id = entry.get(environment)
        if not package_id:
            continue
        if not any((repo_root / folder / name).is_file() for name in MANIFESTS):
            raise SyncError(f"{folder} has no robot.yaml or package.yaml")
        targets.append(Target(folder=folder, package_id=package_id, release=entry.get("release") or Path(folder).name))
    return targets


# --- Selecting what to publish ------------------------------------------------------------------


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit_exists(sha: str, repo_root: Path) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo_root, capture_output=True, check=False).returncode == 0


def changed_since(base: str, path: str, repo_root: Path) -> bool:
    return bool(git("diff", "--name-only", base, "HEAD", "--", path, cwd=repo_root))


def select_by_change(targets: list[Target], base: str | None, mapping_path: Path, repo_root: Path) -> list[Target]:
    if not base or re.fullmatch(r"0+", base) or not commit_exists(base, repo_root):
        print("No usable base commit; publishing every mapped folder.")
        return targets
    if changed_since(base, str(mapping_path), repo_root):
        print("The mapping file changed; publishing every mapped folder.")
        return targets
    return [target for target in targets if changed_since(base, target.folder, repo_root)]


def select_by_tag(targets: list[Target], tag: str) -> list[Target]:
    release, sep, version = tag.rpartition("/")
    if not sep:
        if not re.fullmatch(r"v\d.*", tag):
            raise SyncError(f"tag {tag!r} is not a release tag: use 'v1.2.0' or '<release>/v1.2.0'")
        print(f"Release tag {tag}: publishing every folder that has a package in this environment.")
        return targets
    if not re.fullmatch(r"v\d.*", version):
        raise SyncError(f"tag {tag!r} is not a release tag: use '<release>/v1.2.0'")
    selected = [target for target in targets if target.release == release]
    if not selected:
        known = ", ".join(sorted(t.release for t in targets)) or "none"
        raise SyncError(f"tag {tag!r} names release {release!r}, which no mapped folder has (known: {known})")
    return selected


# --- rcc ----------------------------------------------------------------------------------------


def prepare_rcc(work_dir: Path, url: str, credentials: str) -> list[str]:
    """Return an rcc command prefix configured for the instance and credential, in a private home."""
    os.environ["ROBOCORP_HOME"] = str(work_dir / "robocorp")  # keeps the credential out of shared config
    rcc = shutil.which("rcc")
    if rcc is None:
        version = os.environ.get("RCC_VERSION", DEFAULT_RCC_VERSION)
        rcc = str(work_dir / "rcc")
        urllib.request.urlretrieve(RCC_DOWNLOAD.format(version=version), rcc)
        os.chmod(rcc, os.stat(rcc).st_mode | stat.S_IXUSR)
    print("rcc", subprocess.run([rcc, "version"], check=True, capture_output=True, text=True).stdout.strip())

    # The instance serves its own rcc profile, which points rcc at the instance's rcc endpoint.
    profile = work_dir / "rcc-profile.yaml"
    try:
        urllib.request.urlretrieve(f"{url}/.well-known/rcc-profile.yaml", profile)
    except OSError as exc:
        raise SyncError(f"could not download {url}/.well-known/rcc-profile.yaml: {exc}") from exc
    subprocess.run([rcc, "configuration", "import", "-f", str(profile), "--switch"], check=True, capture_output=True)

    # rcc echoes the credential when adding it, so its output never reaches the log.
    added = subprocess.run(
        [rcc, "configuration", "credentials", credentials, "--account", "ci", "--default"], capture_output=True, check=False
    )
    if added.returncode != 0:
        raise SyncError("rcc did not accept V3_RCC_CREDENTIALS (expected identifier:secret)")
    return [rcc]


# --- Main ---------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--environment", "-e", help="environment in the mapping file, e.g. dev or prod; optional when there is only one")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--base", help="publish folders changed since this commit")
    selection.add_argument("--tag", help="publish the folders this release tag names")
    selection.add_argument("--all", action="store_true", help="publish every mapped folder")
    parser.add_argument("--mapping", type=Path, default=Path(os.environ.get("V3_PACKAGES_FILE", DEFAULT_MAPPING)))
    parser.add_argument("--dry-run", action="store_true", help="print what would be published, without contacting v3")
    args = parser.parse_args(argv)

    repo_root = Path(git("rev-parse", "--show-toplevel", cwd=SCRIPT_DIR))
    mapping_path = args.mapping.resolve()
    mapping = load_mapping(mapping_path)
    if args.environment is None:
        if len(mapping["environments"]) != 1:
            raise SyncError(f"{mapping_path.name} names several environments; choose one with --environment")
        args.environment = next(iter(mapping["environments"]))
    environment = mapping["environments"].get(args.environment)
    if not isinstance(environment, dict) or not environment.get("workspace"):
        raise SyncError(f"environment {args.environment!r} is not in {mapping_path.name}, or has no workspace")
    workspace = environment["workspace"]

    targets = targets_for(mapping, args.environment, repo_root)
    if args.tag:
        targets = select_by_tag(targets, args.tag)
    elif not args.all:
        targets = select_by_change(targets, args.base, mapping_path, repo_root)
    if not targets:
        print(f"No mapped robot folder changed. Nothing to publish to {args.environment}.")
        return 0

    if args.dry_run:
        for target in targets:
            print(f"would publish {target.folder} -> {args.environment} package {target.package_id} in workspace {workspace}")
        return 0

    url = (environment.get("url") or os.environ.get("V3_URL") or "").rstrip("/")
    credentials = os.environ.get("V3_RCC_CREDENTIALS", "")
    if not url:
        raise SyncError("set V3_URL, or a url for the environment in the mapping file")
    if not credentials:
        raise SyncError("V3_RCC_CREDENTIALS is not set")

    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        rcc = prepare_rcc(Path(tmp), url, credentials)
        for target in targets:
            print(f"--- Publishing {target.folder} -> {args.environment} package {target.package_id}", flush=True)
            pushed = subprocess.run(
                [*rcc, "cloud", "push", "--account", "ci", "-d", str(repo_root / target.folder), "-r", target.package_id, "-w", workspace],
                check=False,
            )
            if pushed.returncode == 0:
                print(f"Published {target.folder} to {args.environment} package {target.package_id}.", flush=True)
            else:
                message = f"error: publishing {target.folder} to {args.environment} package {target.package_id} failed."
                print(message, file=sys.stderr, flush=True)
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
