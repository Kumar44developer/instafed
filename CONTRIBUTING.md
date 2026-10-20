# Contributing to Instafeed

Thanks for wanting to make Instafeed better. This guide covers everything
you need to get a change from idea to merged pull request.

## Getting set up

```bash
git clone https://github.com/Kumar44developer/instafed.git
cd instafed
python -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements-dev.txt
cp .env.example .env          # Windows: copy .env.example .env
```

Run the app in **demo mode** while you develop — it serves deterministic
sample data and never touches Instagram:

```bash
INSTAFEED_DEMO=1 uvicorn backend.main:app --reload
```

## The workflow

```bash
make test        # run the test-suite
make lint        # ruff check
make fmt         # ruff format + autofix
make coverage    # coverage report (htmlcov/index.html)
```

## Ground rules

1. **Every change ships with a test.** New endpoint → new test. Bug fix →
   a test that fails before the fix and passes after.
2. **Keep the dependency list short.** The standard library covers hashing,
   tokens and CSV — use it before adding a package.
3. **Never log credentials.** No Instagram password, no session token, no
   `INSTAFEED_SECRET_KEY` in a log line, ever.
4. **Respect Instagram.** All upstream calls go through the throttling
   helper in `backend/instagram.py`. Do not add raw `requests` calls to
   Instagram outside that module.
5. **One concern per module.** `database.py` persists, `instagram.py` talks
   to Instagram, `scheduler.py` orchestrates, `main.py` exposes HTTP.

## Style

- Python 3.10+ syntax, 100-column lines.
- Type hints on public functions.
- Docstrings that explain *why*, not *what*.
- `ruff` is the single source of truth for formatting — never hand-format.

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org):

```
feat: add CSV export for the feed
fix: stop double-counting videos during a poll
docs: explain the demo mode in the README
chore: bump starlette to 1.9.0
```

## Pull requests

- Keep them focused — one logical change per PR.
- Update the README if you change a public API or a setup step.
- Make sure `make test` and `make lint` pass locally; CI runs the same
  commands on Python 3.10, 3.11 and 3.12.
- Describe *why* in the PR body, not only *what*.

## Reporting bugs

Open an issue with:
- what you did,
- what you expected,
- what happened (a stack trace helps a lot),
- your OS, Python version and Instafeed version (`/api/health`).

## Code of conduct

Be kind, assume good faith, and help newcomers. Harassment of any kind is
not tolerated in issues, pull requests or discussions.
