# Secret rotation runbook

Nothing in this repository rotates a secret automatically, and nothing
should. Rotation takes two systems out of agreement for a moment, and the
recovery agent is explicitly forbidden from guessing, copying or rewriting
credentials — so a botched automatic rotation would look exactly like an
attack and would be met with a hard stop rather than a fix.

Every procedure below is manual, ordered so the window where the two sides
disagree is as short as possible, and ends with a verification step.

**Never paste a secret into chat, a ticket, a commit message, or a log.**
The application redacts secret-shaped strings from its own output
(`app/services/secrets.py`), but that is depth, not permission.

---

## MT5 bridge token — `MT5_BRIDGE_TOKEN`

This token was exposed during development and should be rotated before any
public deployment.

1. Generate a new value: `openssl rand -hex 32`.
2. Set it in the **backend** environment (`.env` or the secret store). Do
   not restart yet.
3. Set the same value in the **bridge** configuration on the Windows host.
4. Restart the bridge.
5. Restart or refresh the backend so it reads the new value.
6. Verify: an authenticated call returns data, and `/api/admin/security`
   reports `MT5_BRIDGE_TOKEN: SET`.
   The control centre should show the bridge healthy rather than
   `NEEDS ADMIN`.
7. Invalidate the old value: remove it from any `.env` copy, shell history,
   and CI secret store.

If step 6 fails, the safe state is already the default — the recovery
system classifies an auth failure as `NEEDS_ADMIN`, stops retrying and
pauses automated trading. Fix the mismatch; do not disable authentication.

## Windows agent token — `WINDOWS_AGENT_TOKEN`

Same shape, deliberately a **separate** secret so this rotation cannot
disturb the bridge.

1. `openssl rand -hex 32`.
2. Update the agent's configuration on the Windows host.
3. Update `WINDOWS_AGENT_TOKEN` in the backend environment.
4. Restart the agent, then refresh the backend.
5. Verify with a read-only operation (`CHECK_BRIDGE`) from the control
   centre. It must succeed without an `AUTH_FAILURE`.
6. Remove the old value everywhere it was stored.

## JWT signing secret — `JWT_SECRET`

Rotating this **invalidates every existing session**. Every user, including
you, is signed out.

1. Choose a maintenance window.
2. `openssl rand -hex 32`.
3. Update `JWT_SECRET` and restart the backend.
4. Sign in again and confirm `/api/auth/me` succeeds.
5. Remove the old value.

There is no dual-key grace period today. Adding one means accepting tokens
signed by either key for a short overlap; that is worth building before a
launch with real users, and is not implemented here.

## Database credentials

1. Create the new role or password in PostgreSQL.
2. Update `DATABASE_URL`.
3. **Take a backup first** (`POST /api/admin/backups`), then restart.
4. Verify `/health` and the control centre report the database healthy.
5. Revoke the old credential.

## AI provider key — `ANTHROPIC_API_KEY`

1. Issue a new key with the provider.
2. Update the environment and restart.
3. Verify an analysis run completes.
4. Revoke the old key with the provider.

---

## Checklist before any public deployment

- [ ] `MT5_BRIDGE_TOKEN` rotated (exposed in development)
- [ ] `JWT_SECRET` rotated and not a placeholder
- [ ] `WINDOWS_AGENT_TOKEN` set, or the agent deliberately left unconfigured
- [ ] No `CHANGE_ME` value survives anywhere — `/api/admin/security` shows
      every required secret `SET`, and the deployment check blocks a
      placeholder in production
- [ ] `ALLOW_REAL_TRADING=false` unless real trading has been explicitly
      approved for that deployment
- [ ] A verified backup exists
