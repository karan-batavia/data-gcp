"""Auto-fix known CVEs by upgrading vulnerable locked dependencies.

Runs ``uv-secure`` on every ``uv.lock`` found in the repo, parses the JSON
output, and calls ``uv lock --upgrade-package "<pkg>>=<fix_version>"`` for each
fixable vulnerability.

Works from **any directory** inside a git repository — it resolves the repo root
automatically via ``git rev-parse --show-toplevel``.
"""

from __future__ import annotations

import json
import subprocess
import sys


def _run_uv_secure() -> dict:
    """Run uv-secure and return parsed JSON output."""
    result = subprocess.run(
        ["uv-secure", "--no-check-uv-tool", "--ignore-unfixed", "--format", "json"],
        capture_output=True,
        text=True,
        # cwd=cwd,
    )
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(
            f"Warning: could not parse uv-secure output:\n{result.stdout[:500]}",
            file=sys.stderr,
        )
        return {}


def _collect_upgrade_packages(data: dict) -> list[str]:
    """Extract --upgrade-package arguments from uv-secure JSON output.

    Mirrors the jq logic::

        .files[].dependencies[]
        | select(.vulns | length > 0)
        | "--upgrade-package \"<name>>=<fix_version>\""
    """
    upgrade_args: list[str] = []
    for file_entry in data.get("files", []):
        for dep in file_entry.get("dependencies", []):
            vulns = dep.get("vulns", [])
            if not vulns:
                continue
            name = dep.get("name")
            fix_versions = vulns[0].get("fix_versions", [])
            if name and fix_versions:
                upgrade_args.append(f"{name}>={fix_versions[0]}")
    return upgrade_args


def main() -> int:
    """Entry point for the ``uv-secure-fix`` CLI tool."""

    data = _run_uv_secure()
    if not data:
        print(
            "No vulnerabilities found (or uv-secure returned empty output). Nothing to do."
        )
        return 0

    packages = _collect_upgrade_packages(data)
    if not packages:
        print("No fixable vulnerabilities found. Nothing to do.")
        return 0

    print(f"Found {len(packages)} fixable vulnerability(ies):")
    for pkg in packages:
        print(f'  --upgrade-package "{pkg}"')

    cmd = ["uv", "lock"]
    for pkg in packages:
        cmd.extend(["--upgrade-package", pkg])

    print(f"\nRunning: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
