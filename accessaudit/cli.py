"""cli.py — Command-line interface.

Usage:
    python -m accessaudit.cli check
    python -m accessaudit.cli check --auto-remediate
    python -m accessaudit.cli check --employees path/to.json --access path/to.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import storage
from .pipeline import run_check
from .remediation import LocalConnector

SEVERITY_LABEL = {5: "CRITICAL", 4: "HIGH", 3: "MEDIUM", 2: "LOW", 1: "MINIMAL"}
ISSUE_LABEL = {
    "orphaned_access": "Orphaned Access (ex-employee still has access)",
    "excessive_privilege": "Excessive Privilege",
    "dormant_access": "Dormant Access",
}

DEFAULT_EMPLOYEES = "sample_data/employees.json"
DEFAULT_ACCESS = "sample_data/access_records.json"


def cmd_check(args):
    findings = run_check(args.employees, args.access, Path(args.db) if args.db else None)

    if not findings:
        print("\n✓ No issues found. All access looks accounted for.\n")
        return

    print(f"\nAccessAudit found {len(findings)} issue(s):\n")
    for f in findings:
        label = SEVERITY_LABEL.get(f["severity"], f["severity"])
        print(f"[{label:>8}] {ISSUE_LABEL.get(f['issue_type'], f['issue_type'])}")
        print(f"           {f['employee_name']} <{f['employee_email']}>  →  {f['system']} ({f['access_level']})")
        print(f"           {f['reasoning']}")

        if args.auto_remediate and f["issue_type"] == "orphaned_access":
            _do_action(args, f["id"], f["employee_email"], f["system"], "revoke")
        elif not args.no_prompt:
            _prompt_action(args, f)
        print()


def _prompt_action(args, finding: dict):
    print("           Action? [r]evoke access  [p]assword reset  [s]kip  ", end="")
    try:
        choice = input().strip().lower()
    except EOFError:
        choice = "s"

    if choice == "r":
        _do_action(args, finding["id"], finding["employee_email"], finding["system"], "revoke")
    elif choice == "p":
        _do_action(args, finding["id"], finding["employee_email"], finding["system"], "reset")
    else:
        print("           Skipped.")


def _do_action(args, finding_id: str, user_email: str, system: str, kind: str):
    conn = storage.get_connection(Path(args.db) if args.db else None)
    connector = LocalConnector()

    if kind == "revoke":
        result = connector.revoke_access(user_email, system)
        storage.update_finding_status(conn, finding_id, "revoked")
        print(f"           → Access revoked for {user_email} on {system}.")
    else:
        result = connector.reset_password(user_email, system)
        storage.update_finding_status(conn, finding_id, "password_reset")
        print(f"           → Password reset triggered for {user_email} on {system}.")

    storage.log_action(conn, finding_id, result)
    conn.close()


def cmd_stats(args):
    conn = storage.get_connection(Path(args.db) if args.db else None)
    stats = storage.get_stats(conn)
    print(f"\nOpen findings: {stats['open_total']}  (critical/high: {stats['critical_open']})")
    for issue_type, count in stats["by_issue_type"].items():
        print(f"  {ISSUE_LABEL.get(issue_type, issue_type):<45} {count}")
    print()


def main():
    parser = argparse.ArgumentParser(prog="accessaudit", description="Orphaned access detector")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="Audit HR roster against access records")
    p_check.add_argument("--employees", default=DEFAULT_EMPLOYEES)
    p_check.add_argument("--access", default=DEFAULT_ACCESS)
    p_check.add_argument("--db", default=None)
    p_check.add_argument("--auto-remediate", action="store_true",
                          help="Automatically revoke access for orphaned_access findings")
    p_check.add_argument("--no-prompt", action="store_true",
                          help="Don't prompt interactively; just list findings")
    p_check.set_defaults(func=cmd_check)

    p_stats = sub.add_parser("stats", help="Show current findings summary")
    p_stats.add_argument("--db", default=None)
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
