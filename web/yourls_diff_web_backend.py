#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web backend for YOURLS-diff.

This module contains the download, cache, compare, and artifact-generation
logic used by the web application only.
"""

from __future__ import annotations

import argparse
import dataclasses
import filecmp
import json
import os
import re
import sys
import tempfile
import time
import urllib3
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

GITHUB_API_LATEST = "https://api.github.com/repos/YOURLS/YOURLS/releases/latest"
GITHUB_API_RELEASES = "https://api.github.com/repos/YOURLS/YOURLS/releases"
ZIP_URL_TEMPLATE = "https://github.com/YOURLS/YOURLS/archive/refs/tags/{tag}.zip"

DEFAULT_CACHE_DIR = os.environ.get(
    "YOURLS_DIFF_CACHE_DIR",
    os.path.join(Path.home(), ".cache", "yourls-diff"),
)

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class ReleaseSnapshot:
    tag: str
    archive_path: str
    extract_dir: str
    root_dir: str


@dataclass
class DiffArtifacts:
    old_tag: str
    new_tag: str
    total_old: int
    total_new: int
    changed_files: list[str]
    removed_files: list[str]
    output_dir: str
    zip_path: str | None = None
    manifest_path: str | None = None
    removed_manifest_path: str | None = None
    summary_path: str | None = None
    deploy_script_path: str | None = None
    winscp_script_path: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def safe_name(value: str) -> str:
    sanitized = SAFE_NAME_RE.sub("_", str(value)).strip("._-")
    return sanitized or "unknown"


def _ensure_within_base(path: str, base: str) -> str:
    target_real = os.path.realpath(os.path.expanduser(path))
    base_real = os.path.realpath(os.path.expanduser(base))
    if target_real != base_real and not target_real.startswith(base_real + os.sep):
        raise ValueError(f"Refusing to create directory outside allowed base: {path}")
    return target_real


def ensure_dir(path: str, base_dir: str | None = None) -> str:
    base_root = base_dir or os.path.dirname(os.path.realpath(DEFAULT_CACHE_DIR))
    safe_path = _ensure_within_base(path, base_root)
    os.makedirs(safe_path, exist_ok=True)
    return safe_path


def safe_filename_component(value: str) -> str:
    return safe_name(value)


def default_zip_name(old_tag: str, new_tag: str) -> str:
    safe_old = safe_filename_component(old_tag)
    safe_new = safe_filename_component(new_tag)
    return f"YOURLS-update-{safe_old}-to-{safe_new}.zip"


def artifact_paths(output_dir: str, old_tag: str, new_tag: str, output_name: str | None = None) -> dict[str, str]:
    safe_old = safe_filename_component(old_tag)
    safe_new = safe_filename_component(new_tag)
    zip_name = output_name or default_zip_name(old_tag, new_tag)
    base_name = os.path.splitext(zip_name)[0]
    return {
        "zip_name": zip_name,
        "zip_path": os.path.join(output_dir, zip_name),
        "manifest_path": os.path.join(output_dir, base_name + ".txt"),
        "removed_manifest_path": os.path.join(output_dir, base_name + ".removed.txt"),
        "summary_path": os.path.join(output_dir, base_name + ".summary.txt"),
        "deploy_script_path": os.path.join(output_dir, f"YOURLS-deploy-{safe_old}-to-{safe_new}.sh"),
        "winscp_script_path": os.path.splitext(os.path.join(output_dir, base_name + ".removed.txt"))[0] + ".winscp.txt",
    }


def read_manifest(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def cache_path(*parts: str, cache_dir: str | None = None) -> str:
    base = cache_dir or DEFAULT_CACHE_DIR
    return os.path.join(base, *parts)


def safe_cache_path(path: str, cache_dir: str | None = None) -> str:
    return _ensure_within_base(path, cache_dir or DEFAULT_CACHE_DIR)


def download_zip(tag: str, dest_path: str, verify_ssl: bool) -> str:
    """Download the ZIP archive for the given YOURLS release tag to dest_path."""
    url = ZIP_URL_TEMPLATE.format(tag=tag)
    print(f"→ Downloading {tag} from {url}")
    r = requests.get(url, stream=True, verify=verify_ssl, timeout=(10, 120))
    r.raise_for_status()
    safe_dest = safe_cache_path(dest_path)
    with open(safe_dest, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            if chunk:
                f.write(chunk)
    return safe_dest


def get_latest_tag(verify_ssl: bool) -> str:
    """Fetch the tag name of the latest YOURLS release from the GitHub API."""
    r = requests.get(GITHUB_API_LATEST, verify=verify_ssl, timeout=30)
    r.raise_for_status()
    return r.json()["tag_name"]


def fetch_releases(verify_ssl: bool, cache_dir: str | None = None, max_age_seconds: int = 900) -> list[dict[str, object]]:
    """Fetch stable YOURLS releases and cache the metadata on disk."""
    cache_file = cache_path("releases.json", cache_dir=cache_dir)
    if os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < max_age_seconds:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

    releases: list[dict[str, object]] = []
    page = 1
    while True:
        r = requests.get(
            GITHUB_API_RELEASES,
            params={"per_page": 100, "page": page},
            verify=verify_ssl,
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        for item in batch:
            if item.get("draft") or item.get("prerelease"):
                continue
            tag = item.get("tag_name")
            if not tag:
                continue
            releases.append(
                {
                    "tag_name": tag,
                    "name": item.get("name") or tag,
                    "published_at": item.get("published_at"),
                    "html_url": item.get("html_url"),
                }
            )
        if len(batch) < 100:
            break
        page += 1

    ensure_dir(os.path.dirname(cache_file), base_dir=cache_dir or DEFAULT_CACHE_DIR)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(releases, f, indent=2)
    return releases


def extract_zip(zip_path: str, extract_to: str) -> str:
    """Extract the ZIP file at zip_path into extract_to and return the main folder path."""
    safe_extract_to = ensure_dir(extract_to, base_dir=os.path.dirname(extract_to))
    marker = safe_cache_path(os.path.join(safe_extract_to, ".complete"), cache_dir=os.path.dirname(safe_extract_to))
    if os.path.exists(marker):
        subdirs = [d for d in os.listdir(safe_extract_to) if os.path.isdir(os.path.join(safe_extract_to, d))]
        return safe_cache_path(os.path.join(safe_extract_to, subdirs[0]), cache_dir=safe_extract_to) if len(subdirs) == 1 else safe_extract_to

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(safe_extract_to)
    with open(marker, "w", encoding="utf-8") as f:
        f.write(str(time.time()))
    subdirs = [d for d in os.listdir(safe_extract_to) if os.path.isdir(os.path.join(safe_extract_to, d))]
    return safe_cache_path(os.path.join(safe_extract_to, subdirs[0]), cache_dir=safe_extract_to) if len(subdirs) == 1 else safe_extract_to


def count_all_files(base_dir: str) -> int:
    """Count all files under base_dir."""
    return sum(len(files) for _, _, files in os.walk(base_dir))


def collect_changed(old_dir: str, new_dir: str) -> list[str]:
    """Return a list of new or modified file paths in new_dir compared to old_dir."""
    changed: list[str] = []
    comp = filecmp.dircmp(old_dir, new_dir)
    for name in comp.right_only:
        path = os.path.join(new_dir, name)
        if os.path.isfile(path):
            changed.append(path)
        else:
            for root, _, files in os.walk(path):
                for fn in files:
                    changed.append(os.path.join(root, fn))
    for name in comp.diff_files:
        changed.append(os.path.join(new_dir, name))
    for sub in comp.common_dirs:
        changed += collect_changed(os.path.join(old_dir, sub), os.path.join(new_dir, sub))
    return changed


def collect_removed(old_dir: str, new_dir: str) -> list[str]:
    """Return a list of file paths that exist in old_dir but not in new_dir."""
    removed: list[str] = []
    comp = filecmp.dircmp(old_dir, new_dir)
    for name in comp.left_only:
        path = os.path.join(old_dir, name)
        if os.path.isfile(path):
            removed.append(path)
        else:
            for root, _, files in os.walk(path):
                for fn in files:
                    removed.append(os.path.join(root, fn))
    for sub in comp.common_dirs:
        removed += collect_removed(os.path.join(old_dir, sub), os.path.join(new_dir, sub))
    return removed


def write_manifest(changed_files: Iterable[str], new_root: str, manifest_path: str) -> None:
    """Write a manifest file listing the changed files (paths relative to new_root)."""
    ensure_dir(os.path.dirname(manifest_path), base_dir=os.path.dirname(manifest_path))
    with open(manifest_path, "w", encoding="utf-8") as mf:
        for full in sorted(changed_files):
            rel = os.path.relpath(full, new_root)
            mf.write(rel + "\n")
    print(f"→ Manifest saved to {manifest_path}")


def write_removed_manifest(removed_files: Iterable[str], old_root: str, removed_manifest_path: str) -> None:
    ensure_dir(os.path.dirname(removed_manifest_path), base_dir=os.path.dirname(removed_manifest_path))
    with open(removed_manifest_path, "w", encoding="utf-8") as rmf:
        for full in sorted(removed_files):
            rel = os.path.relpath(full, old_root)
            rmf.write(rel + "\n")
    print(f"→ Removed files found, list saved to {removed_manifest_path}")


def safe_output_path(path: str, output_dir: str) -> str:
    return _ensure_within_base(path, output_dir)


def open_output_text(path: str, output_dir: str, mode: str):
    return open(safe_output_path(path, output_dir), mode, encoding="utf-8")


def output_path_exists(path: str, output_dir: str) -> bool:
    return os.path.exists(safe_output_path(path, output_dir))


def read_output_manifest(path: str, output_dir: str) -> list[str]:
    with open_output_text(path, output_dir, "r") as f:
        return [line.strip() for line in f if line.strip()]


def create_diff_zip(changed_files: Iterable[str], new_root: str, zip_output: str) -> None:
    """Create a ZIP archive containing only the changed files."""
    ensure_dir(os.path.dirname(zip_output), base_dir=os.path.dirname(zip_output))
    print(f"→ Creating package {zip_output}")
    count = 0
    with zipfile.ZipFile(zip_output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for full_path in changed_files:
            rel = os.path.relpath(full_path, new_root)
            z.write(full_path, rel)
            count += 1
    print(f"→ Done. ZIP contains {count} file.")


def generate_deploy_script(
    old_tag: str,
    new_tag: str,
    zip_name: str,
    manifest_name: str,
    removed_manifest_name: str | None = None,
    only_removed: bool = False,
    output_dir: str | None = None,
) -> str:
    """
    Generate a Bash deployment script. If only_removed is True, include only the file removal logic.
    """
    safe_old = safe_filename_component(old_tag)
    safe_new = safe_filename_component(new_tag)
    script_filename = os.path.join(output_dir or os.getcwd(), f"YOURLS-deploy-{safe_old}-to-{safe_new}.sh")
    lines = [
        "#!/bin/bash",
        "",
        "# Deployment script generated by YOURLS-diff",
        "# Update the variables below before running.",
        "",
        "# Check if ssh is installed",
        "if ! command -v ssh >/dev/null 2>&1; then",
        "  echo \"Error: ssh is not installed or not found in PATH.\"",
        "  exit 1",
        "fi",
        "",
        f"REMOVED_MANIFEST=\"{removed_manifest_name or ''}\"",
        "TARGET_DIR=\"/var/www/yourls\"      # <-- Update this with your server's path",
        "REMOTE_USER=\"user\"               # <-- Update with your SSH user",
        "REMOTE_HOST=\"yourserver.com\"     # <-- Update with your server hostname or IP",
        "",
        "# Pass --dry-run as first argument to simulate the deploy",
        "DRYRUN=\"\"",
        "if [ \"$1\" == \"--dry-run\" ]; then",
        "  DRYRUN=\"--dry-run\"",
        "  echo \"Running in DRY-RUN mode. No files will be copied or deleted.\"",
        "fi",
        "",
    ]

    if only_removed:
        lines += [
            "# Remove deleted files from remote (if any)",
            "if [[ -f \"$REMOVED_MANIFEST\" ]]; then",
            "  echo \"→ Removing obsolete files...\"",
            "  while IFS= read -r file; do",
            "    ssh \"$REMOTE_USER@$REMOTE_HOST\" \"rm -f '$TARGET_DIR/$file'\"",
            "  done < \"$REMOVED_MANIFEST\"",
            "fi",
        ]
    else:
        lines += [
            f"ZIP_FILE=\"{zip_name}\"",
            f"MANIFEST=\"{manifest_name}\"",
            "TEMP_DIR=\"./__deploy_temp\"",
            "",
            "# Clean and unzip the patch",
            "rm -rf \"$TEMP_DIR\"",
            "mkdir -p \"$TEMP_DIR\"",
            "unzip -q \"$ZIP_FILE\" -d \"$TEMP_DIR\"",
            "echo \"→ Files extracted into $TEMP_DIR\"",
            "",
            "# Upload changed/added files",
            "echo \"→ Uploading changed files...\"",
            "while IFS= read -r file; do",
            "  rsync -avz $DRYRUN \"$TEMP_DIR/$file\" \"$REMOTE_USER@$REMOTE_HOST:$TARGET_DIR/$file\"",
            "done < \"$MANIFEST\"",
            "",
            "# Remove deleted files",
            "if [[ -f \"$REMOVED_MANIFEST\" ]]; then",
            "  echo \"→ Removing obsolete files...\"",
            "  while IFS= read -r file; do",
            "    ssh \"$REMOTE_USER@$REMOTE_HOST\" \"rm -f '$TARGET_DIR/$file'\"",
            "  done < \"$REMOVED_MANIFEST\"",
            "fi",
            "",
            "# Clean up",
            "rm -rf \"$TEMP_DIR\"",
        ]

    lines += ["echo \"Deployment completed!\""]

    with open(script_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.chmod(script_filename, 0o755)
    print(f"→ Deployment script generated: {script_filename}")
    return script_filename


def generate_winscp_script(removed_manifest_path: str, remote_base_path: str, host: str, user: str) -> str:
    """
    Generate a WinSCP script to download and delete files listed in the removed manifest.
    """
    manifest_path = safe_output_path(removed_manifest_path, os.path.dirname(removed_manifest_path))
    script_dir = os.path.dirname(manifest_path)
    local_backup_dir = ensure_dir(os.path.join(script_dir, "removed_backup"), base_dir=script_dir)
    script_name = safe_output_path(os.path.splitext(manifest_path)[0] + ".winscp.txt", script_dir)

    with open_output_text(manifest_path, script_dir, "r") as f:
        files = [line.strip() for line in f if line.strip()]

    with open_output_text(script_name, script_dir, "w") as wsc:
        wsc.write("option batch on\n")
        wsc.write("option confirm off\n")
        wsc.write(f"open sftp://{user}@{host}/\n")
        wsc.write(f"cd {remote_base_path}\n")
        wsc.write(f"lcd {local_backup_dir}\n")

        for rel_path in files:
            unix_path = rel_path.replace("\\", "/")
            local_path = _ensure_within_base(os.path.join(local_backup_dir, rel_path), local_backup_dir)
            ensure_dir(os.path.dirname(local_path), base_dir=local_backup_dir)
            wsc.write(f"get \"{unix_path}\" \"{rel_path}\"\n")

        for rel_path in files:
            unix_path = rel_path.replace("\\", "/")
            wsc.write(f"rm \"{unix_path}\"\n")

        wsc.write("close\n")
        wsc.write("exit\n")

    print(f"→ WinSCP script generated: {script_name}")
    print(f"→ Backup folder prepared at: {local_backup_dir}")
    return script_name


def prepare_release(tag: str, verify_ssl: bool, cache_dir: str | None = None) -> ReleaseSnapshot:
    """Download and extract a release, reusing cached artifacts when present."""
    root_cache = cache_dir or DEFAULT_CACHE_DIR
    archives_dir = ensure_dir(cache_path("archives", cache_dir=root_cache), base_dir=root_cache)
    extracted_dir = ensure_dir(cache_path("extracted", cache_dir=root_cache), base_dir=root_cache)
    safe_tag = safe_filename_component(tag)
    archive_path = os.path.join(archives_dir, f"{safe_tag}.zip")
    extract_dir = os.path.join(extracted_dir, safe_tag)
    if not os.path.exists(archive_path):
        download_zip(tag, archive_path, verify_ssl)
    root_dir = extract_zip(archive_path, extract_dir)
    return ReleaseSnapshot(tag=tag, archive_path=archive_path, extract_dir=extract_dir, root_dir=root_dir)


def resolve_tag(tag: str | None, verify_ssl: bool) -> str:
    if not tag or tag == "latest":
        latest = get_latest_tag(verify_ssl)
        print(f"→ No target version specified, using latest: {latest}")
        return latest
    return tag


def run_diff(
    old_tag: str,
    new_tag: str | None,
    verify_ssl: bool,
    output_dir: str,
    output_name: str | None = None,
    summary: bool = False,
    only_removed: bool = False,
    winscp: bool = False,
    cache_dir: str | None = None,
    remote_base_path: str = "/var/www/yourls",
    remote_host: str = "yourserver.com",
    remote_user: str = "youruser",
) -> DiffArtifacts:
    """Run the full compare and artifact generation workflow."""
    new_tag = resolve_tag(new_tag, verify_ssl)
    if old_tag == new_tag:
        raise ValueError(f"Old tag '{old_tag}' and new tag '{new_tag}' are identical. Nothing to do.")

    ensure_dir(output_dir, base_dir=output_dir)
    paths = artifact_paths(output_dir, old_tag, new_tag, output_name=output_name)
    zip_name = paths["zip_name"]
    manifest_path = paths["manifest_path"]
    removed_manifest_path = paths["removed_manifest_path"]
    summary_path = paths["summary_path"]
    deploy_path = paths["deploy_script_path"]
    winscp_path = paths["winscp_script_path"]

    old_release = prepare_release(old_tag, verify_ssl, cache_dir=cache_dir)
    new_release = prepare_release(new_tag, verify_ssl, cache_dir=cache_dir)

    baseline_ready = output_path_exists(paths["zip_path"], output_dir) and output_path_exists(manifest_path, output_dir) and output_path_exists(deploy_path, output_dir)
    if only_removed:
        baseline_ready = output_path_exists(removed_manifest_path, output_dir) and output_path_exists(deploy_path, output_dir)

    if baseline_ready:
        changed = read_output_manifest(manifest_path, output_dir) if not only_removed else []
        removed = read_output_manifest(removed_manifest_path, output_dir) if output_path_exists(removed_manifest_path, output_dir) else []
        if only_removed:
            if winscp and not output_path_exists(winscp_path, output_dir):
                winscp_path = generate_winscp_script(
                    removed_manifest_path=removed_manifest_path,
                    remote_base_path=remote_base_path,
                    host=remote_host,
                    user=remote_user,
                )
            return DiffArtifacts(
                old_tag=old_tag,
                new_tag=new_tag,
                total_old=count_all_files(old_release.root_dir),
                total_new=count_all_files(new_release.root_dir),
                changed_files=[],
                removed_files=removed,
                output_dir=output_dir,
                removed_manifest_path=removed_manifest_path if output_path_exists(removed_manifest_path, output_dir) else None,
                deploy_script_path=deploy_path if output_path_exists(deploy_path, output_dir) else None,
                winscp_script_path=winscp_path if output_path_exists(winscp_path, output_dir) else None,
                message="Reused existing removed-file artifacts.",
            )

        if summary and not output_path_exists(summary_path, output_dir):
            removed_files = read_output_manifest(removed_manifest_path, output_dir) if output_path_exists(removed_manifest_path, output_dir) else []
            summary_path = safe_output_path(summary_path, output_dir)
            with open(summary_path, "w", encoding="utf-8") as rb:
                rb.write(f"# YOURLS Patch Summary (from {old_tag} version to {new_tag})\n\n")
                rb.write(f"Number of files in OLD: {count_all_files(old_release.root_dir)}\n")
                rb.write(f"Number of files in NEW: {count_all_files(new_release.root_dir)}\n")
                rb.write(f"Number of files in generated patch ZIP: {len(changed)}\n\n")

                rb.write("Modified files:\n")
                for rel in changed:
                    rb.write(rel + "\n")

                if removed_files:
                    rb.write("\nRemoved files:\n")
                    for rel in removed_files:
                        rb.write(rel + "\n")
                else:
                    rb.write("\nNo files were removed between the two versions.\n")
            print(f"→ Release summary saved to {summary_path}")

        return DiffArtifacts(
            old_tag=old_tag,
            new_tag=new_tag,
            total_old=count_all_files(old_release.root_dir),
            total_new=count_all_files(new_release.root_dir),
            changed_files=changed,
            removed_files=read_output_manifest(removed_manifest_path, output_dir) if output_path_exists(removed_manifest_path, output_dir) else [],
            output_dir=output_dir,
            zip_path=paths["zip_path"] if output_path_exists(paths["zip_path"], output_dir) else None,
            manifest_path=manifest_path if output_path_exists(manifest_path, output_dir) else None,
            removed_manifest_path=removed_manifest_path if output_path_exists(removed_manifest_path, output_dir) else None,
            summary_path=summary_path if output_path_exists(summary_path, output_dir) else None,
            deploy_script_path=deploy_path if output_path_exists(deploy_path, output_dir) else None,
            winscp_script_path=winscp_path if output_path_exists(winscp_path, output_dir) else None,
            message="Reused existing patch artifacts.",
        )

    print("→ Comparing directories…")
    removed = collect_removed(old_release.root_dir, new_release.root_dir)
    if only_removed:
        if removed:
            write_removed_manifest(removed, old_release.root_dir, removed_manifest_path)
            deploy_path = generate_deploy_script(
                old_tag=old_tag,
                new_tag=new_tag,
                zip_name=zip_name,
                manifest_name=os.path.basename(manifest_path),
                removed_manifest_name=os.path.basename(removed_manifest_path),
                only_removed=True,
                output_dir=output_dir,
            )
            winscp_path = None
            if winscp:
                winscp_path = generate_winscp_script(
                    removed_manifest_path=removed_manifest_path,
                    remote_base_path=remote_base_path,
                    host=remote_host,
                    user=remote_user,
                )
            return DiffArtifacts(
                old_tag=old_tag,
                new_tag=new_tag,
                total_old=count_all_files(old_release.root_dir),
                total_new=count_all_files(new_release.root_dir),
                changed_files=[],
                removed_files=removed,
                output_dir=output_dir,
                removed_manifest_path=removed_manifest_path,
                deploy_script_path=deploy_path,
                winscp_script_path=winscp_path,
                message="Removed-file list generated.",
            )
        raise ValueError("No files to remove from OLD to NEW.")

    changed = collect_changed(old_release.root_dir, new_release.root_dir)
    total_old = count_all_files(old_release.root_dir)
    total_new = count_all_files(new_release.root_dir)

    print(f" - Files in ({old_tag}): {total_old}")
    print(f" - Files in ({new_tag}): {total_new}")
    print(f" - Files added / modified: {len(changed)}")
    print(f" - Files removed: {len(removed)}\n")

    if not changed and not removed:
        raise ValueError("No differences found.")

    write_manifest(changed, new_release.root_dir, manifest_path)
    if removed:
        write_removed_manifest(removed, old_release.root_dir, removed_manifest_path)
    else:
        removed_manifest_path = None

    zip_path = os.path.join(output_dir, zip_name)
    create_diff_zip(changed, new_release.root_dir, zip_path)
    deploy_path = generate_deploy_script(
        old_tag=old_tag,
        new_tag=new_tag,
        zip_name=zip_name,
        manifest_name=os.path.basename(manifest_path),
        removed_manifest_name=os.path.basename(removed_manifest_path) if removed_manifest_path else None,
        output_dir=output_dir,
    )

    if summary:
        summary_path = safe_output_path(summary_path, output_dir)
        with open(summary_path, "w", encoding="utf-8") as rb:
            rb.write(f"# YOURLS Patch Summary (from {old_tag} version to {new_tag})\n\n")
            rb.write(f"Number of files in OLD: {total_old}\n")
            rb.write(f"Number of files in NEW: {total_new}\n")
            rb.write(f"Number of files in generated patch ZIP: {len(changed)}\n\n")

            rb.write("Modified files:\n")
            for full in sorted(changed):
                rel = os.path.relpath(full, new_release.root_dir)
                rb.write(rel + "\n")

            if removed:
                rb.write("\nRemoved files:\n")
                for full in sorted(removed):
                    rel = os.path.relpath(full, old_release.root_dir)
                    rb.write(rel + "\n")
            else:
                rb.write("\nNo files were removed between the two versions.\n")

        print(f"→ Release summary saved to {summary_path}")
    else:
        summary_path = None

    return DiffArtifacts(
        old_tag=old_tag,
        new_tag=new_tag,
        total_old=total_old,
        total_new=total_new,
        changed_files=changed,
        removed_files=removed,
        output_dir=output_dir,
        zip_path=zip_path,
        manifest_path=manifest_path,
        removed_manifest_path=removed_manifest_path,
        summary_path=summary_path,
        deploy_script_path=deploy_path,
        message="Patch generated successfully.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a ZIP package with differences between two YOURLS releases and an external manifest file."
    )
    parser.add_argument("--old", required=True, help="Tag of the starting release (e.g. '1.8.10').")
    parser.add_argument("--new", default=None, help="Tag of the target release (if omitted, 'latest' is used).")
    parser.add_argument("--output", default=None, help="Output ZIP filename (default: YOURLS-update-OLD-to-NEW.zip).")
    parser.add_argument("--no-verify", action="store_true", help="Disable SSL certificate verification (not recommended).")
    parser.add_argument("--summary", action="store_true", help="Generate a summary text file with patch details (e.g. for use in release notes).")
    parser.add_argument("--only-removed", action="store_true", help="Only generate the .removed.txt file (if any). Skip all other outputs. Also generates a deployment script to remove the files from the server.")
    parser.add_argument("--winscp", action="store_true", help="Generate a .winscp.txt script to download and delete the removed files (requires --only-removed)")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help="Directory used to cache YOURLS release archives.")
    parser.add_argument("--output-dir", default=os.getcwd(), help="Directory used to write generated artifacts.")
    args = parser.parse_args(argv)

    verify_ssl = not args.no_verify
    print(f"→ SSL verification is {'disabled' if not verify_ssl else 'enabled'}.")
    if args.no_verify:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        result = run_diff(
            old_tag=args.old,
            new_tag=args.new,
            verify_ssl=verify_ssl,
            output_dir=args.output_dir,
            output_name=args.output,
            summary=args.summary,
            only_removed=args.only_removed,
            winscp=args.winscp,
            cache_dir=args.cache_dir,
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    if args.only_removed:
        if result.removed_files:
            print("→ You can use the generated script to remove the files from the server.")
        else:
            print("→ No files to remove from OLD to NEW. Exiting.")
            return 0
    else:
        print(f"All set: upload {os.path.basename(result.zip_path or '')} via FTP and review {os.path.basename(result.manifest_path or '')} for the list of changed files.")
        print(f"You can also use the generated YOURLS-deploy-{result.old_tag}-to-{result.new_tag}.sh script to upload the files via rsync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
