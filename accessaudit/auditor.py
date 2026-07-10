"""auditor.py — Cross-references HR roster against system access records to
find orphaned, dormant, and excessive access.

Hybrid engine, same philosophy as InboxPilot:
1. Rule engine (default) — deterministic date/status comparison. Always available,
   no API key, no network required. This is what actually catches the issues —
   it's a matching problem, not a fuzzy classification problem.
2. LLM engine (optional) — when ANTHROPIC_API_KEY is set, used only to generate
   a clearer, more specific human-readable "reasoning" string for each finding.
   The severity/decision itself always comes from the deterministic rule engine,
   never from the LLM — you don't want a security finding's existence to depend
   on a model call succeeding.
"""

from __future__ import annotations

import os
import json
from datetime import date, datetime
from typing import Optional

from .models import Employee, AccessRecord, Finding

DORMANT_THRESHOLD_DAYS = 90

# Rough "typical" access ceiling per department — anything above this on a
# system outside the department's normal scope is flagged as excessive.
HIGH_SENSITIVITY_SYSTEMS = {"AWS Console", "Payroll System", "Admin Panel", "Production Database"}


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def _days_since(d: Optional[date], today: date) -> Optional[int]:
    if d is None:
        return None
    return (today - d).days


def _rule_based_finding(employee: Employee, record: AccessRecord, today: date) -> Optional[Finding]:
    finding_id = f"f_{record.id}"

    # 1. Orphaned access — terminated employee with any live access. Always critical.
    if employee.status == "terminated":
        term_date = _parse_date(employee.termination_date)
        days_since_term = _days_since(term_date, today) if term_date else None
        severity = 5 if record.access_level == "admin" else 4
        reasoning = (
            f"{employee.name} was terminated"
            + (f" {days_since_term} day(s) ago" if days_since_term is not None else "")
            + f" but still has {record.access_level} access to {record.system}."
        )
        return Finding(
            id=finding_id, employee_email=employee.email, employee_name=employee.name,
            system=record.system, access_level=record.access_level,
            issue_type="orphaned_access", severity=severity, reasoning=reasoning, engine="rules",
        )

    # 2. Excessive privilege — admin access to a high-sensitivity system outside
    #    what's typical (kept simple/explainable: any non-IT/non-Engineering dept
    #    holding admin on a high-sensitivity system is flagged for review).
    if (
        record.access_level == "admin"
        and record.system in HIGH_SENSITIVITY_SYSTEMS
        and employee.department not in {"IT", "Engineering", "Security"}
    ):
        return Finding(
            id=finding_id, employee_email=employee.email, employee_name=employee.name,
            system=record.system, access_level=record.access_level,
            issue_type="excessive_privilege", severity=3,
            reasoning=(
                f"{employee.name} ({employee.department}) holds admin access to "
                f"{record.system}, which is unusual for this department and worth reviewing."
            ),
            engine="rules",
        )

    # 3. Dormant access — active employee, valid access, but unused for a long time.
    last_used = _parse_date(record.last_used_date)
    days_idle = _days_since(last_used, today)
    if days_idle is not None and days_idle >= DORMANT_THRESHOLD_DAYS:
        return Finding(
            id=finding_id, employee_email=employee.email, employee_name=employee.name,
            system=record.system, access_level=record.access_level,
            issue_type="dormant_access", severity=2,
            reasoning=(
                f"{employee.name} has not used {record.system} in {days_idle} days "
                f"(access granted {record.granted_date})."
            ),
            engine="rules",
        )
    if last_used is None:
        return Finding(
            id=finding_id, employee_email=employee.email, employee_name=employee.name,
            system=record.system, access_level=record.access_level,
            issue_type="dormant_access", severity=2,
            reasoning=(
                f"{employee.name} was granted access to {record.system} on "
                f"{record.granted_date} but has no recorded usage since."
            ),
            engine="rules",
        )

    return None  # clean — no finding


def _llm_reasoning(employee: Employee, record: AccessRecord, base_finding: Finding) -> Optional[str]:
    """Optionally sharpens the reasoning text using the Anthropic API.
    Never changes severity or issue_type — only the explanation text. Returns
    None on any failure so callers keep the rule-based reasoning."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    prompt = f"""You are a security analyst. In ONE concise sentence, explain why this
finding matters and what the risk is, for a security dashboard. Do not invent facts
beyond what's given.

Employee: {employee.name}, {employee.department}, status={employee.status}
System: {record.system}, access_level={record.access_level}
Issue type: {base_finding.issue_type}
Base facts: {base_finding.reasoning}

Respond with ONLY the sentence, no preamble."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        return text or None
    except Exception:
        return None


def run_audit(employees: list[Employee], access_records: list[AccessRecord],
              today: Optional[date] = None) -> list[Finding]:
    today = today or date.today()
    employee_by_email = {e.email: e for e in employees}

    findings: list[Finding] = []
    for record in access_records:
        employee = employee_by_email.get(record.user_email)
        if employee is None:
            continue  # access record for an unknown user — out of scope for this pass

        finding = _rule_based_finding(employee, record, today)
        if finding is None:
            continue

        sharper_reasoning = _llm_reasoning(employee, record, finding)
        if sharper_reasoning:
            finding.reasoning = sharper_reasoning
            finding.engine = "llm"

        findings.append(finding)

    findings.sort(key=lambda f: -f.severity)
    return findings
