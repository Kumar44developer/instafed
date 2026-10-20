# Security Policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 2.x     | :white_check_mark: |
| < 2.0   | :x:                |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Email **kumarswamyry82@gmail.com** with:

- a description of the vulnerability and its impact,
- the steps to reproduce it,
- any proof-of-concept code.

You will get an acknowledgement within **72 hours** and a status update
within **7 days**. Confirmed issues are fixed in a release as soon as
possible, and you are credited in the release notes unless you prefer
otherwise.

## How Instafeed protects you

| Concern                | Measure                                                        |
| ---------------------- | -------------------------------------------------------------- |
| Passwords              | PBKDF2-HMAC-SHA256, 240 000 iterations, 16-byte random salt      |
| Sessions               | Stateless HMAC-SHA256 signed tokens, 30-day expiry              |
| Token transport        | `Authorization: Bearer` header only — never a query string       |
| Secret management      | `INSTAFEED_SECRET_KEY` from the environment; auto-generated fallback persisted with `0600`-style isolation |
| SQL injection          | Parameterised queries everywhere                                 |
| XSS                    | Every user-supplied string is escaped before being rendered     |
| Rate limiting          | Minimum delay between upstream Instagram calls + exponential back-off on HTTP 429 |
| Secrets in git         | `.env`, `*.secret`, `instafeed.db*` are git-ignored              |
| Data isolation         | Every query is scoped to the authenticated `user_id`             |

## Deployment checklist

Before exposing Instafeed to the internet:

- [ ] Set `INSTAFEED_SECRET_KEY` to a long, random value.
- [ ] Set `INSTAFEED_CORS_ORIGINS` to your real origin(s) — never `*`.
- [ ] Terminate TLS in front of the app (a reverse proxy or platform load balancer).
- [ ] Use a dedicated, unprivileged system user for the process.
- [ ] Back up the SQLite database (`instafeed.db`) regularly.
- [ ] Consider putting the app behind rate limiting at the proxy level.

## Responsible use

Instafeed is a personal, self-hosted tool. Respect Instagram's Terms of
Service and the rights of content creators. Do not use it to redistribute
content at scale or to circumvent platform access controls.
