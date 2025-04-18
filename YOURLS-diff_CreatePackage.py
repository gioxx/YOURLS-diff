#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YOURLS-diff_CreatePackage.py

Generate a ZIP "patch" and an external manifest listing only the changed files
between two YOURLS releases, ready for FTP upload.

Usage:
    python YOURLS-diff_CreatePackage.py --old <OLD_TAG> [--new <NEW_TAG>] [--output <ZIP_NAME>] [--no-verify]

Options:
    --old        Tag of the starting release (required, e.g. 1.8.10)
    --new        Tag of the target release (default: latest)
    --output     Output ZIP filename (default: YOURLS-update-OLD-to-NEW.zip)
    --no-verify  Disable SSL certificate verification (not recommended)

Author: Your Name
Repo:   https://github.com/gioxx/YOURLS-diff
License: MIT
"""
import argparse
import os
import sys
import tempfile
import requests
import urllib3
import zipfile
import filecmp

GITHUB_API_LATEST = "https://api.github.com/repos/YOURLS/YOURLS/releases/latest"
ZIP_URL_TEMPLATE = "https://github.com/YOURLS/YOURLS/archive/refs/tags/{tag}.zip"

def download_zip(tag, dest_path, verify_ssl):
    """Download the ZIP archive for the given YOURLS release tag to dest_path."""
    url = ZIP_URL_TEMPLATE.format(tag=tag)
    print(f"→ Downloading {tag} from {url}")
    r = requests.get(url, stream=True, verify=verify_ssl)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            f.write(chunk)
    return dest_path

def get_latest_tag(verify_ssl):
    """Fetch the tag name of the latest YOURLS release from the GitHub API."""
    r = requests.get(GITHUB_API_LATEST, verify=verify_ssl)
    r.raise_for_status()
    return r.json()["tag_name"]

def extract_zip(zip_path, extract_to):
    """Extract the ZIP file at zip_path into extract_to and return the main folder path."""
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_to)
    subdirs = [d for d in os.listdir(extract_to) if os.path.isdir(os.path.join(extract_to, d))]
    return os.path.join(extract_to, subdirs[0]) if len(subdirs) == 1 else extract_to

def collect_changed(old_dir, new_dir):
    """Return a list of new or modified file paths in new_dir compared to old_dir."""
    changed = []
    comp = filecmp.dircmp(old_dir, new_dir)
    # Files only in new_dir
    for name in comp.right_only:
        path = os.path.join(new_dir, name)
        if os.path.isfile(path):
            changed.append(path)
        else:
            # Recurse into new directories
            for root, _, files in os.walk(path):
                for fn in files:
                    changed.append(os.path.join(root, fn))
    # Files present in both but different
    for name in comp.diff_files:
        changed.append(os.path.join(new_dir, name))
    # Recurse into common subdirectories
    for sub in comp.common_dirs:
        changed += collect_changed(
            os.path.join(old_dir, sub),
            os.path.join(new_dir, sub)
        )
    return changed

def write_manifest(changed_files, new_root, manifest_path):
    """Write a manifest file listing the changed files (paths relative to new_root)."""
    with open(manifest_path, "w", encoding="utf-8") as mf:
        for full in sorted(changed_files):
            rel = os.path.relpath(full, new_root)
            mf.write(rel + "\n")
    print(f"→ Manifest saved to {manifest_path}")

def create_diff_zip(changed_files, new_root, zip_output):
    """Create a ZIP archive containing only the changed files."""
    print(f"→ Creating package {zip_output}")
    with zipfile.ZipFile(zip_output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for full_path in changed_files:
            rel = os.path.relpath(full_path, new_root)
            z.write(full_path, rel)
    print("→ Done.")

def main():
    parser = argparse.ArgumentParser(
        description="Prepare a ZIP package with differences between two YOURLS releases and an external manifest file."
    )
    parser.add_argument("--old", required=True,
                        help="Tag of the starting release (e.g. '1.8.10').")
    parser.add_argument("--new", default=None,
                        help="Tag of the target release (if omitted, 'latest' is used).")
    parser.add_argument("--output", default=None,
                        help="Output ZIP filename (default: YOURLS-update-OLD-to-NEW.zip).")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Disable SSL certificate verification (not recommended)."
    )
    args = parser.parse_args()

    # Determine SSL verification setting
    verify_ssl = not args.no_verify
    print(f"→ SSL verification is {'disabled' if not verify_ssl else 'enabled'}.")
    if args.no_verify:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Determine tags
    old_tag = args.old
    if args.new:
        new_tag = args.new
    else:
        new_tag = get_latest_tag(verify_ssl)
        print(f"→ No target version specified, using latest: {new_tag}")

    # Exit early if tags are identical
    if old_tag == new_tag:
        print(f"Old tag '{old_tag}' and new tag '{new_tag}' are identical. Nothing to do.")
        sys.exit(0)

    # Determine output names
    zip_name = args.output or f"YOURLS-update-{old_tag}-to-{new_tag}.zip"
    manifest_name = os.path.splitext(zip_name)[0] + ".txt"

    with tempfile.TemporaryDirectory() as tmp:
        old_zip = os.path.join(tmp, f"{old_tag}.zip")
        new_zip = os.path.join(tmp, f"{new_tag}.zip")
        download_zip(old_tag, old_zip, verify_ssl)
        download_zip(new_tag, new_zip, verify_ssl)

        old_dir = extract_zip(old_zip, os.path.join(tmp, "old"))
        new_dir = extract_zip(new_zip, os.path.join(tmp, "new"))

        print("→ Comparing directories…")
        changed = collect_changed(old_dir, new_dir)
        if not changed:
            print("No differences found. Exiting.")
            sys.exit(0)

        # Generate external manifest
        manifest_path = os.path.join(os.getcwd(), manifest_name)
        write_manifest(changed, new_dir, manifest_path)

        # Create the diff ZIP
        create_diff_zip(changed, new_dir, zip_name)

    print(f"All set: upload {zip_name} via FTP and review {manifest_name} for the list of changed files.")

if __name__ == "__main__":
    main()
