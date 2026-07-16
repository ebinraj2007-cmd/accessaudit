# Security & Pre-Deployment Notes

AccessAudit is a single-operator tool (one IT/security owner auditing their own
org). It defaults to local use on `127.0.0.1`. Each item below maps to the
standard pre-deployment checklist.

## 1. Authorization
One tenant (the operator), so authorization is a shared operator token rather
than per-row ownership. All **state-changing** endpoints (uploads, sample load,
revoke, reset-password, dismiss, clear) require it when `ACCESSAUDIT_TOKEN` is
set; clients send `Authorization: Bearer <token>`. Unset = trusted local mode
(startup warning). Read-only endpoints stay open for the dashboard to render.
```bash
export ACCESSAUDIT_TOKEN="$(openssl rand -hex 32)"
```

## 2. Credential hygiene
No user accounts / reset links, so nothing to expire. The operator token is the
only secret: keep it in an env var / secret manager, never in git, rotate by
regenerating and restarting. (Note: the app's *own* "reset password" button is a
remediation action against the audited system, unrelated to auth.)

## 3. Input validation
- Uploaded files are read fully into memory, so they are **size-capped**
  (`ACCESSAUDIT_MAX_UPLOAD`, default 5 MB) → returns 413 if exceeded.
- `kind` is whitelisted to `employees`/`access`.
- SQL uses **parameterised queries only** (`storage.py`) — no injection.
- The dashboard escapes every value with `escapeHtml()` before inserting into
  the DOM — hostile names/emails in an uploaded file cannot execute (XSS-safe).

## 4. CORS
Restricted to `ACCESSAUDIT_ORIGINS` (default localhost), not `*`; GET/POST only.

## 5. Rate limiting
Per-IP sliding window: 120/min default, strict 15/min on uploads, sample-load
and clear. Tunable via `ACCESSAUDIT_RATE` / `ACCESSAUDIT_RATE_STRICT`.

## 6. Error handling
Validation errors return the importer's own human-readable message (safe). Any
**unexpected** exception is logged server-side and returns a generic
`Internal server error` — no stack traces or internals leak to the client.

## 7. Database performance
Targeted indexes: `findings(status)`, `findings(severity, detected_at)` for the
main list, and `action_log(performed_at)` / `action_log(finding_id)` for the
audit trail. Not every column — extra indexes only slow writes.

## 8. Logging & monitoring
Structured JSON-line request logs (path, status, latency) and a `GET /healthz`
readiness probe that checks the database.

## 9. Rollback
See `DEPLOY.md`.
