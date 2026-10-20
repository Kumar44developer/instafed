## 🚀 Welcome to Instafeed!

Thanks for taking the time to contribute. This project is **completely open
source** and every improvement — from a typo fix to a whole new provider —
is welcome.

### Where things live

| Path | What it holds |
|---|---|
| `backend/` | The FastAPI application, storage layer and Instagram providers |
| `frontend/` | The zero-build single-page app (HTML + CSS + vanilla JS) |
| `tests/` | The pytest suite — hermetic, never touches the network |
| `scripts/` | One-shot poll, demo seeding |
| `assets/` | Logo and banner artwork |

### Getting set up in two minutes

```bash
make dev      # create .venv and install everything
make test     # make sure it works
make run      # http://localhost:8000
```

Working on the UI? Run with `INSTAFEED_DEMO=1` so you never hit Instagram
while you design.

### House rules

1. **Tests first.** A bug fix ships with a test that failed before it.
2. **Standard library first.** `hashlib`, `hmac`, `csv` and `json` cover
   almost everything we need.
3. **Never log secrets.** No tokens, no passwords, no `INSTAFEED_SECRET_KEY`.
4. **Be polite to Instagram.** All upstream traffic goes through the
   throttling helper in `backend/instagram.py`.
5. **One concern per module** — persist in `database.py`, fetch in
   `instagram.py`, orchestrate in `scheduler.py`, serve in `main.py`.

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full guide, and
[`SECURITY.md`](SECURITY.md) before reporting anything security-sensitive.

### Where to ask questions

- **Bugs** → [open an issue](https://github.com/Kumar44developer/instafed/issues/new?template=bug_report.yml)
- **Ideas** → [open an issue](https://github.com/Kumar44developer/instafed/issues/new?template=feature_request.yml)
- **Security** → email, do not open an issue

Happy hacking! 🚀
