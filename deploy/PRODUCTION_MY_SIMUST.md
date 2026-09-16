# My SIMUST production — my.simust.com

## Canonical login URL (use this on simust.com)

**https://my.simust.com/login**

- DNS A record `my.simust.com` → `157.180.47.98` (DNS only / orange-cloud off) is required.
- Caddy terminates TLS and sets HSTS. HTTP requests to `my.simust.com` redirect to HTTPS.
- Public mode serves the portal; `/` redirects to `/login`.

Also valid: `https://my.simust.com/register`, `https://my.simust.com/dashboard` (auth required), `https://my.simust.com/privacy`.

## Application hostname recognition

| Setting | Value |
|---------|--------|
| `SIMUST_PUBLIC_MODE` | `1` |
| `SIMUST_PUBLIC_HOSTNAMES` | `my.simust.com` (default) |
| `SIMUST_PUBLIC_ORIGINS` | `https://simust.com,https://www.simust.com,https://my.simust.com` |
| `SIMUST_PUBLIC_BASE_URL` | `https://my.simust.com` |
| Portal client | treats `my.simust.com` as root (`PORTAL_ROOT=''`) |

## Security posture (implemented)

| Area | Status |
|------|--------|
| Authentication | PBKDF2 passwords, HMAC bearer tokens, auth rate limits |
| Organisation / roles | player (self), coach (team), manager (club), admin (all) via `can_access_player` |
| Player assignments | Club/team scoped on the server; lab-only routes blocked in PUBLIC_MODE |
| Youth / guardian consent | Players under 16 must supply guardian email + consent checkbox; stored server-side |
| Server-side authorisation | Token required on public host; reservation/report APIs scoped to viewer |
| HTTPS / HSTS | Caddy on `my.simust.com` (`max-age=31536000; includeSubDomains`) |
| PII in URLs | Reservation cancel no longer puts `username` in the query string; auth uses Bearer header |
| Client logging | Portal startup does not log account identifiers |

## Responsibilities

| Responsibility | Owner |
|----------------|--------|
| Hosting (Hetzner VPS `157.180.47.98`, Caddy, uvicorn, OS patches) | SIMUST platform / lab ops |
| DNS for `my.simust.com` | Domain owner (Webreact / simust.com DNS) |
| Marketing site redirects (`simust.com` → portal) | simust.com website agent (see `deploy/SIMUST_COM_AGENT.txt`) |
| Monitoring (uptime HTTPS `/login`, disk, systemd `simust` + `caddy`) | SIMUST platform / lab ops |
| Backups (`users.json`, reports, `.env` secrets, Caddy certs) | SIMUST platform / lab ops |
| Application support & bugfix | SIMUST engineering |
| Data correction / export / deletion requests | SIMUST data controller via `privacy@simust.com` (process per privacy policy) |

## Deploy checklist after DNS

```bash
# On VPS
cd /opt/simust && git pull
# Ensure .env contains:
#   SIMUST_PUBLIC_MODE=1
#   SIMUST_PUBLIC_BASE_URL=https://my.simust.com
#   SIMUST_PUBLIC_ORIGINS=https://simust.com,https://www.simust.com,https://my.simust.com
#   SIMUST_SESSION_SECRET=<strong secret>
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # if not already
sudo systemctl restart caddy simust
curl -I https://my.simust.com/login
```
