# Deploying AccessAudit (with a rollback path)

Stateless FastAPI app; all state is the SQLite file under `data/accessaudit.db`.

## Environment
```bash
export ACCESSAUDIT_TOKEN="$(openssl rand -hex 32)"
export ACCESSAUDIT_ORIGINS="https://audit.yourdomain.com"
export ACCESSAUDIT_MAX_UPLOAD=5242880
export ACCESSAUDIT_RATE_STRICT=15
```

## Blue-green deploy
Two identical instances share the same persistent DB volume; a load balancer
routes to one at a time.

1. **Blue** is live. Deploy the new build to **green** on a second port.
2. Smoke-test green: `curl -f http://127.0.0.1:<green>/healthz`
3. Flip the load balancer from blue to green. Keep blue warm.
4. Watch error rate / logs for a few minutes.

## Rollback
If green misbehaves, flip the load balancer **back to blue** — no rebuild, no
data migration (shared DB). The schema is created with `CREATE TABLE/INDEX IF
NOT EXISTS` only (additive), so an older build keeps working against a newer DB,
which is what makes instant rollback safe. Snapshot the DB before any
destructive migration.

## Monitoring
- Readiness: `GET /healthz`
- Alert on: 5xx rate, `429` spikes, `/healthz` failures.
