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
    --old           Tag of the starting release (required, e.g. 1.8.10)
    --new           Tag of the target release (default: latest)
    --output        Output ZIP filename (default: YOURLS-update-OLD-to-NEW.zip)
    --no-verify     Disable SSL certificate verification (not recommended)
    --summary       Generate a summary text file with patch details (e.g. for use in release notes)
    --only-removed  Only generate the .removed.txt file (if any). Skip all other outputs. Also generates a deployment script to remove the files from the server.
    --winscp        Generate a .winscp.txt script to download and delete the removed files (requires --only-removed)
    --help          Show this help message and exit

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

def generate_deploy_script(old_tag, new_tag, zip_name, manifest_name,
                           removed_manifest_name=None, only_removed=False):
    """
    Generate a Bash deployment script. If only_removed is True, include only the file removal logic.
    """
    script_filename = f"YOURLS-deploy-{old_tag}-to-{new_tag}.sh"
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
        f"REMOVED_MANIFEST=\"{removed_manifest_name}\"",
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

def generate_winscp_script(removed_manifest_path, remote_base_path, host, user):
    """
    Generate a WinSCP script to download and delete files listed in the removed manifest,
    preserving folder structure locally, under a 'removed_backup' directory near the Python script.
    """
    import pathlib

    # Directory of this Python script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_backup_dir = os.path.join(script_dir, "removed_backup")

    # Make sure the base local backup dir exists
    os.makedirs(local_backup_dir, exist_ok=True)

    # WinSCP script filename (next to manifest)
    script_name = os.path.splitext(removed_manifest_path)[0] + ".winscp.txt"

    # Load removed files
    with open(removed_manifest_path, "r", encoding="utf-8") as f:
        files = [line.strip() for line in f if line.strip()]

    # Generate WinSCP script
    with open(script_name, "w", encoding="utf-8") as wsc:
        wsc.write("option batch on\n")
        wsc.write("option confirm off\n")
        wsc.write(f"open sftp://{user}@{host}/\n")
        wsc.write(f"cd {remote_base_path}\n")
        wsc.write(f"lcd {local_backup_dir}\n")

        for rel_path in files:
            unix_path = rel_path.replace("\\", "/")
            local_path = os.path.join(local_backup_dir, rel_path)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            wsc.write(f"get \"{unix_path}\" \"{rel_path}\"\n")

        for rel_path in files:
            unix_path = rel_path.replace("\\", "/")
            wsc.write(f"rm \"{unix_path}\"\n")

        wsc.write("close\n")
        wsc.write("exit\n")

    print(f"→ WinSCP script generated: {script_name}")
    print(f"→ Backup folder prepared at: {local_backup_dir}")

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
    parser.add_argument("--no-verify",action="store_true",
                        help="Disable SSL certificate verification (not recommended).")
    parser.add_argument("--summary",action="store_true",
                        help="Generate a summary text file with patch details (e.g. for use in release notes).")
    parser.add_argument("--only-removed",action="store_true",
                        help="Only generate the .removed.txt file (if any). Skip all other outputs. Also generates a deployment script to remove the files from the server.")
    parser.add_argument("--winscp", action="store_true",
                        help="Generate a .winscp.txt script to download and delete the removed files (requires --only-removed)")
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
    base_name = os.path.splitext(zip_name)[0]
    manifest_name = base_name + ".txt"
    removed_manifest = base_name + ".removed.txt"
    release_body_path = base_name + ".summary.txt"

    with tempfile.TemporaryDirectory() as tmp:
        old_zip = os.path.join(tmp, f"{old_tag}.zip")
        new_zip = os.path.join(tmp, f"{new_tag}.zip")
        download_zip(old_tag, old_zip, verify_ssl)
        download_zip(new_tag, new_zip, verify_ssl)

        old_dir = extract_zip(old_zip, os.path.join(tmp, "old"))
        new_dir = extract_zip(new_zip, os.path.join(tmp, "new"))

        print("→ Comparing directories…")
        removed = collect_removed(old_dir, new_dir)

        if args.only_removed:
            if removed:
                with open(removed_manifest, "w", encoding="utf-8") as rmf:
                    for full in sorted(removed):
                        rel = os.path.relpath(full, old_dir)
                        rmf.write(rel + "\n")
                print(f"→ Removed files found, list saved to {removed_manifest}")

                # Always generate deploy.sh in --only-removed mode
                generate_deploy_script(
                    old_tag=old_tag,
                    new_tag=new_tag,
                    zip_name=zip_name,
                    manifest_name=manifest_name,
                    removed_manifest_name=removed_manifest,
                    only_removed=True
                )
                print("→ You can use the generated script to remove the files from the server.")

                if args.winscp:
                    generate_winscp_script(
                        removed_manifest_path=removed_manifest,
                        remote_base_path="/var/www/yourls",
                        host="yourserver.com",
                        user="youruser"
                    )

                sys.exit(0)
            else:
                print("→ No files to remove from OLD to NEW. Exiting.")
                sys.exit(0)
        
        changed = collect_changed(old_dir, new_dir)
        total_old = count_all_files(old_dir)
        total_new = count_all_files(new_dir)

        print(f" - Files in ({old_tag}): {total_old}")
        print(f" - Files in ({new_tag}): {total_new}")
        print(f" - Files added / modified: {len(changed)}")
        print(f" - Files removed: {len(removed)}\n")

        if not changed and not removed:
            print("No differences found. Exiting.")
            sys.exit(0)

        # Generate external manifest
        manifest_path = os.path.join(os.getcwd(), manifest_name)
        write_manifest(changed, new_dir, manifest_path)

        # Create .removed.txt if needed
        if removed:
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
                else:
                    rb.write("\nNo files were removed between the two versions.\n")

            print(f"→ Release summary saved to {release_body_path}")

    print(f"All set: upload {zip_name} via FTP and review {manifest_name} for the list of changed files.")
    print(f"You can also use the generated YOURLS-deploy-{old_tag}-to-{new_tag}.sh script to upload the files via rsync.")

if __name__ == "__main__":
    main()
