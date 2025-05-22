#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YOURLS-diff_CreatePackage.py

Generate a ZIP "patch" and an external manifest listing only the changed files
between two YOURLS releases (and removed files, if any), ready for FTP upload.
This Python script also generate a Bash deployment script to upload the changed files using rsync.

Usage:
    python YOURLS-diff_CreatePackage.py --old <OLD_TAG> [--new <NEW_TAG>] [--output <ZIP_NAME>] [--no-verify] [--summary]
    
Example:
    python YOURLS-diff_CreatePackage.py --old 1.8.10

Options:
    --old        Tag of the starting release (required, e.g. 1.8.10)
    --new        Tag of the target release (default: latest)
    --output     Output ZIP filename (default: YOURLS-update-OLD-to-NEW.zip)
    --no-verify  Disable SSL certificate verification (not recommended)
    --summary    Generate a summary text file with patch details (e.g. for use in release notes)

Author: Gioxx
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

def count_all_files(base_dir):
    """Count all files under base_dir."""
    return sum(len(files) for _, _, files in os.walk(base_dir))

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

def collect_removed(old_dir, new_dir):
    """Return a list of file paths that exist in old_dir but not in new_dir."""
    removed = []
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
        removed += collect_removed(
            os.path.join(old_dir, sub),
            os.path.join(new_dir, sub)
        )
    return removed

def write_manifest(changed_files, new_root, manifest_path):
    """Write a manifest file listing the changed files (paths relative to new_root)."""
    with open(manifest_path, "w", encoding="utf-8") as mf:
        for full in sorted(changed_files):
            rel = os.path.relpath(full, new_root)
            mf.write(rel + "\n")
    print(f"→ Manifest saved to {manifest_path}")

# def create_diff_zip(changed_files, new_root, zip_output):
#     """Create a ZIP archive containing only the changed files."""
#     print(f"→ Creating package {zip_output}")
#     with zipfile.ZipFile(zip_output, "w", compression=zipfile.ZIP_DEFLATED) as z:
#         for full_path in changed_files:
#             rel = os.path.relpath(full_path, new_root)
#             z.write(full_path, rel)
#     print("→ Done.")

def create_diff_zip(changed_files, new_root, zip_output):
    """Create a ZIP archive containing only the changed files."""
    print(f"→ Creating package {zip_output}")
    count = 0
    with zipfile.ZipFile(zip_output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for full_path in changed_files:
            rel = os.path.relpath(full_path, new_root)
            z.write(full_path, rel)
            count += 1
    print(f"→ Done. ZIP contains {count} file.")

def generate_deploy_script(old_tag, new_tag, zip_name, manifest_name, removed_manifest_name=None):
    """Generate a Bash deployment script to upload changed files using rsync."""
    script_filename = f"YOURLS-deploy-{old_tag}-to-{new_tag}.sh"
    temp_dir = "__deploy_temp"

    lines = [
        "#!/bin/bash",
        "",
        "# Deployment script generated by YOURLS-diff",
        "# Update the variables below before running.",
        "",
        "# Check if rsync is installed",
        "if ! command -v rsync >/dev/null 2>&1; then",
        "  echo \"Error: rsync is not installed or not found in PATH.\"",
        "  exit 1",
        "fi",
        "",
        "# Check if ssh is installed",
        "if ! command -v ssh >/dev/null 2>&1; then",
        "  echo \"Error: ssh is not installed or not found in PATH.\"",
        "  exit 1",
        "fi",
        "",
        f"MANIFEST=\"{manifest_name}\"",
        f"REMOVED_MANIFEST=\"{removed_manifest_name}\"" if removed_manifest_name else "# REMOVED_MANIFEST=\"\"",
        f"ZIP_FILE=\"{zip_name}\"",
        "TARGET_DIR=\"/var/www/yourls\"      # <-- Update this with your server's path",
        "REMOTE_USER=\"user\"               # <-- Update with your SSH user",
        "REMOTE_HOST=\"yourserver.com\"     # <-- Update with your server hostname or IP",
        f"TEMP_DIR=\"./{temp_dir}\"",
        "",
        "# Pass --dry-run as first argument to simulate the deploy",
        "DRYRUN=\"\"",
        "if [ \"$1\" == \"--dry-run\" ]; then",
        "  DRYRUN=\"--dry-run\"",
        "  echo \"Running in DRY-RUN mode. No files will be copied or deleted.\"",
        "fi",
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
        "# Remove deleted files from remote (if any)",
        "if [[ -f \"$REMOVED_MANIFEST\" ]]; then",
        "  echo \"→ Removing obsolete files...\"",
        "  while IFS= read -r file; do",
        "    ssh \"$REMOTE_USER@$REMOTE_HOST\" \"rm -f '$TARGET_DIR/$file'\"",
        "  done < \"$REMOVED_MANIFEST\"",
        "fi",
        "",
        "# Clean up temp directory",
        "rm -rf \"$TEMP_DIR\"",
        "echo \"Deployment completed!\""
    ]

    with open(script_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.chmod(script_filename, 0o755)
    print(f"→ Deployment script generated: {script_filename}")

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
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Generate a summary text file with patch details (e.g. for use in release notes)."
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

        # print("→ Comparing directories…")
        # changed = collect_changed(old_dir, new_dir)
        # if not changed:
        #     print("No differences found. Exiting.")
        #     sys.exit(0)

        print("→ Comparing directories…")
        changed = collect_changed(old_dir, new_dir)
        removed = collect_removed(old_dir, new_dir)

        total_old = count_all_files(old_dir)
        total_new = count_all_files(new_dir)

        print(f" - Files in ({old_tag}): {total_old}")
        print(f" - Files in ({new_tag}): {total_new}")
        print(f" - Files added / modified: {len(changed)}")
        print(f" - Files removed: {len(removed)}\n")

        if not changed and not removed:
            print("No differences found. Exiting.")
            sys.exit(0)

        # # Generate external manifest
        # manifest_path = os.path.join(os.getcwd(), manifest_name)
        # write_manifest(changed, new_dir, manifest_path)

        # Generate external manifest
        manifest_path = os.path.join(os.getcwd(), manifest_name)
        write_manifest(changed, new_dir, manifest_path)

        # Create .removed.txt if needed
        if removed:
            removed_manifest = os.path.splitext(zip_name)[0] + ".removed.txt"
            with open(removed_manifest, "w", encoding="utf-8") as rmf:
                for full in sorted(removed):
                    rel = os.path.relpath(full, old_dir)
                    rmf.write(rel + "\n")
            print(f"→ Removed files found, list saved to {removed_manifest}")

        # Create the diff ZIP
        create_diff_zip(changed, new_dir, zip_name)

        # Generate the deployment script
        generate_deploy_script(old_tag, new_tag, zip_name, manifest_name, removed_manifest if removed else None)

        # Create a summary file if requested
        if args.summary:
            release_body_path = os.path.splitext(zip_name)[0] + ".summary.txt"
            with open(release_body_path, "w", encoding="utf-8") as rb:
                rb.write(f"# YOURLS Patch Summary (from {old_tag} version to {new_tag})\n\n")
                rb.write(f"Number of files in OLD: {total_old}\n")
                rb.write(f"Number of files in NEW: {total_new}\n")
                rb.write(f"Number of files in generated patch ZIP: {len(changed)}\n\n")

                rb.write("Modified files:\n")
                for full in sorted(changed):
                    rel = os.path.relpath(full, new_dir)
                    rb.write(rel + "\n")

                if removed:
                    rb.write("\nRemoved files:\n")
                    for full in sorted(removed):
                        rel = os.path.relpath(full, old_dir)
                        rb.write(rel + "\n")

            print(f"→ Release summary saved to {release_body_path}")

    print(f"All set: upload {zip_name} via FTP and review {manifest_name} for the list of changed files.")
    print(f"You can also use the generated YOURLS-deploy-{old_tag}-to-{new_tag}.sh script to upload the files via rsync.")

if __name__ == "__main__":
    main()
