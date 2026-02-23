#!/usr/bin/env python3
"""
HoudiniMCP installer — sets up auto-start for the Houdini addon.

Usage:
    python install.py                      # install (auto-detect Houdini prefs)
    python install.py --houdini-pref-dir DIR  # install with explicit prefs path
    python install.py --uninstall          # remove package + 123.py hook
    python install.py --dry-run            # show what would be done without writing
"""

import argparse
import json
import os
import re
import sys
import glob

HOOK_START = "# --- HoudiniMCP auto-start hook ---"
HOOK_END = "# --- end HoudiniMCP hook ---"

HOOK_BLOCK = """\
# --- HoudiniMCP auto-start hook ---
import os as _mcp_os
if _mcp_os.environ.get("HOUDINIMCP_AUTO_START") == "1":
    _mcp_root = _mcp_os.environ.get("HOUDINIMCP_ROOT", "")
    if _mcp_root:
        import sys as _mcp_sys
        if _mcp_root not in _mcp_sys.path:
            _mcp_sys.path.insert(0, _mcp_root)
        try:
            import houdinimcp_addon
            houdinimcp_addon.init_houdinimcp()
        except Exception as _mcp_e:
            print(f"[HoudiniMCP] Auto-start failed: {_mcp_e}")
# --- end HoudiniMCP hook ---
"""


def find_houdini_pref_dir():
    """Auto-detect the Houdini user preferences directory."""
    env_dir = os.environ.get("HOUDINI_USER_PREF_DIR")
    if env_dir and os.path.isdir(env_dir):
        return env_dir

    if sys.platform == "win32":
        docs = os.path.join(os.path.expanduser("~"), "Documents")
    else:
        docs = os.path.expanduser("~")

    # Find all houdini* directories and pick the highest numeric version
    def _version_key(path):
        name = os.path.basename(path)
        m = re.search(r'(\d+(?:\.\d+)*)', name)
        if m:
            return tuple(int(x) for x in m.group(1).split('.'))
        return (0,)

    candidates = sorted(
        [c for c in glob.glob(os.path.join(docs, "houdini*")) if os.path.isdir(c)],
        key=_version_key,
        reverse=True,
    )
    for c in candidates:
        return c

    return None


def write_package(pref_dir, repo_root, dry_run=False):
    """Write the houdinimcp.json package file."""
    pkg_dir = os.path.join(pref_dir, "packages")
    pkg_path = os.path.join(pkg_dir, "houdinimcp.json")

    # Use forward slashes for Houdini compatibility
    repo_path_clean = repo_root.replace("\\", "/")

    pkg_data = {
        "env": [
            {"HOUDINIMCP_ROOT": repo_path_clean},
            {"HOUDINIMCP_AUTO_START": "1"},
        ]
    }

    if dry_run:
        print(f"[DRY RUN] Would write package to: {pkg_path}")
        print(f"          Contents: {json.dumps(pkg_data, indent=4)}")
        return

    os.makedirs(pkg_dir, exist_ok=True)
    with open(pkg_path, "w") as f:
        json.dump(pkg_data, f, indent=4)
    print(f"[OK] Package written: {pkg_path}")


def patch_123(pref_dir, dry_run=False):
    """Add the auto-start hook to 123.py (idempotent)."""
    scripts_dir = os.path.join(pref_dir, "scripts")
    py123_path = os.path.join(scripts_dir, "123.py")

    existing_content = ""
    if os.path.exists(py123_path):
        with open(py123_path, "r") as f:
            existing_content = f.read()

    # If markers exist, replace the block
    if HOOK_START in existing_content:
        start_idx = existing_content.index(HOOK_START)
        end_idx = existing_content.index(HOOK_END) + len(HOOK_END)
        new_content = existing_content[:start_idx] + HOOK_BLOCK.rstrip() + existing_content[end_idx:]
        action = "replaced"
    else:
        # Append to the end
        if existing_content and not existing_content.endswith("\n"):
            existing_content += "\n"
        new_content = existing_content + "\n" + HOOK_BLOCK
        action = "appended"

    if dry_run:
        print(f"[DRY RUN] Would {action} hook in: {py123_path}")
        return

    os.makedirs(scripts_dir, exist_ok=True)
    with open(py123_path, "w") as f:
        f.write(new_content)
    print(f"[OK] Hook {action} in: {py123_path}")


def remove_package(pref_dir, dry_run=False):
    """Remove the houdinimcp.json package file."""
    pkg_path = os.path.join(pref_dir, "packages", "houdinimcp.json")
    if os.path.exists(pkg_path):
        if dry_run:
            print(f"[DRY RUN] Would remove: {pkg_path}")
        else:
            os.remove(pkg_path)
            print(f"[OK] Removed: {pkg_path}")
    else:
        print(f"[SKIP] Package not found: {pkg_path}")


def remove_hook(pref_dir, dry_run=False):
    """Remove the auto-start hook from 123.py."""
    py123_path = os.path.join(pref_dir, "scripts", "123.py")
    if not os.path.exists(py123_path):
        print(f"[SKIP] 123.py not found: {py123_path}")
        return

    with open(py123_path, "r") as f:
        content = f.read()

    if HOOK_START not in content:
        print(f"[SKIP] No HoudiniMCP hook found in: {py123_path}")
        return

    start_idx = content.index(HOOK_START)
    end_idx = content.index(HOOK_END) + len(HOOK_END)

    # Remove the block and any surrounding blank lines
    before = content[:start_idx].rstrip("\n")
    after = content[end_idx:].lstrip("\n")
    new_content = before
    if after:
        new_content += "\n" + after
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    if dry_run:
        print(f"[DRY RUN] Would remove hook from: {py123_path}")
    else:
        with open(py123_path, "w") as f:
            f.write(new_content)
        print(f"[OK] Hook removed from: {py123_path}")


def main():
    parser = argparse.ArgumentParser(description="HoudiniMCP installer")
    parser.add_argument(
        "--houdini-pref-dir",
        help="Path to Houdini user preferences directory "
             "(e.g. ~/Documents/houdini21.0)",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the package and 123.py hook",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    args = parser.parse_args()

    # Resolve Houdini prefs directory
    pref_dir = args.houdini_pref_dir or find_houdini_pref_dir()
    if not pref_dir:
        print(
            "ERROR: Could not find Houdini user preferences directory.\n"
            "Use --houdini-pref-dir to specify it manually.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.isdir(pref_dir):
        print(f"ERROR: Directory does not exist: {pref_dir}", file=sys.stderr)
        sys.exit(1)

    repo_root = os.path.dirname(os.path.abspath(__file__))

    print(f"Houdini prefs: {pref_dir}")
    print(f"Repo root:     {repo_root}")
    print()

    if args.uninstall:
        remove_package(pref_dir, dry_run=args.dry_run)
        remove_hook(pref_dir, dry_run=args.dry_run)
        print("\nUninstall complete.")
    else:
        write_package(pref_dir, repo_root, dry_run=args.dry_run)
        patch_123(pref_dir, dry_run=args.dry_run)
        print("\nInstall complete. Restart Houdini to auto-start the MCP addon.")


if __name__ == "__main__":
    main()
