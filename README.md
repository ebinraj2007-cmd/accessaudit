# ⛊ AccessAudit — Orphaned Access & Offboarding Console

AccessAudit answers one question companies consistently get wrong: **when someone leaves, does their access actually get revoked?**

Run a check, and it cross-references your HR roster against system access records to surface exactly what manual audits miss:

- **Orphaned access** — an employee left, but their login to Payroll, AWS, the Admin Panel, etc. is still active
- **Excessive privilege** — someone holds admin rights to a sensitive system well outside their role's norm
- **Dormant access** — valid, active employee, but access to a system that hasn't been touched in 90+ days

Every finding is actionable on the spot: **Revoke Access**, **Reset Password**, or **Dismiss** — each one logged to a real audit trail.

## Why this exists

Offboarding checklists get followed for the obvious stuff (laptop, badge) and quietly skipped for the dozen SaaS tools and internal systems someone had access to. That gap is one of the most common, most expensive, and most preventable security failures in real companies — and almost nobody has a system that just tells them where the gaps are.

## How it works — hybrid engine, same philosophy as InboxPilot

1. **Rule engine (always on)** — deterministic comparison of HR status vs. access records. This is what actually finds the issues; it's a matching problem, not a guessing problem, so it doesn't need an LLM to be accurate.
2. **LLM engine (optional)** — set `ANTHROPIC_API_KEY` and each finding's explanation gets sharpened by Claude into a clearer, more specific sentence. It only ever rewrites the *explanation* — the underlying severity and decision always come from the deterministic rule engine, so a security finding never depends on an API call succeeding.

## Quick start

```bash
git clone https://github.com/ebinraj2007-cmd/accessaudit.git
cd accessaudit
pip install -r requirements.txt

# CLI — run a check right now
python -m accessaudit.cli check

# Web dashboard
uvicorn webapp.main:app --reload
# then open http://127.0.0.1:8000, click "Run Check"
```

The CLI is interactive by default — for each finding it asks `[r]evoke  [p]assword reset  [s]kip`. Use `--no-prompt` for a read-only listing, or `--auto-remediate` to automatically revoke access for every orphaned-access finding.

## What "Revoke" and "Reset Password" actually do

Out of the box, AccessAudit ships with a `LocalConnector` that performs the action for real within its own system of record — it updates the finding's status and writes a timestamped entry to the audit trail. It's honest about what it does: this demo has no credentials to your real Okta/Azure AD/Google Workspace, so it doesn't pretend to call them.

For production use, connect a real identity provider: `accessaudit/remediation.py` includes a documented `OktaConnector` shape — set `OKTA_DOMAIN` and `OKTA_API_TOKEN`, swap the connector in `webapp/main.py` and `cli.py`, and the exact same UI/CLI now performs real revocations. Nothing else in the app changes.

## Enabling the LLM engine (optional)

```bash
export ANTHROPIC_API_KEY=your-key-here
python -m accessaudit.cli check
```

No key set → the rule engine's reasoning is used as-is. No code changes needed either way.

## Architecture

```
sample_data/employees.json  ─┐
                              ├──▶  auditor.py  ──▶  storage.py (SQLite)
sample_data/access_records.json ┘   (rules or Claude)      │
                                                     ┌───────┴────────┐
                                                CLI ◀┤                ├▶ FastAPI dashboard
                                                     └────────────────┘
                                                             │
                                                    remediation.py
                                                (LocalConnector / OktaConnector)
```

- `accessaudit/auditor.py` — the hybrid detection engine
- `accessaudit/remediation.py` — pluggable action connector (revoke / reset)
- `accessaudit/storage.py` — SQLite persistence: findings + a real action audit trail
- `accessaudit/pipeline.py` — orchestrates ingest → audit → store
- `accessaudit/cli.py` — interactive command-line interface
- `webapp/` — FastAPI backend + vanilla JS/CSS dashboard with live Revoke/Reset/Dismiss actions and an audit trail drawer

## Using your own company data

Export your HR system and access/IAM logs into this shape:

**employees.json**
```json
{ "id": "u001", "name": "...", "email": "...", "department": "...", "role": "...",
  "status": "active | terminated", "termination_date": "YYYY-MM-DD or null" }
```

**access_records.json**
```json
{ "id": "a001", "user_email": "...", "system": "...", "access_level": "admin | standard | read-only",
  "granted_date": "YYYY-MM-DD", "last_used_date": "YYYY-MM-DD or null" }
```

```bash
python -m accessaudit.cli check --employees path/to/employees.json --access path/to/access.json
```

## Running tests

```bash
pytest tests/ -v
```

19 tests, covering the detection rules, severity scoring, the LLM fallback path (mocked, no real API key needed), and the remediation/audit-trail logic.

## Tech stack

Python · FastAPI · SQLite · Anthropic Claude API (optional) · vanilla JS/CSS · pytest · GitHub Actions

## License

MIT
