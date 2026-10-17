# CV Forge

Tailor a LaTeX resume to a job description using only what your master resume documents.
CV Forge imports your resume, analyses a job description, shows which requirements your
experience supports (with the exact excerpts), asks an AI model for grounded rewrites, checks
every rewrite deterministically, and produces an ATS-oriented `.tex` and PDF from the changes
you approve.

It runs locally. The only outbound traffic is the AI request you explicitly ask for.

## Requirements

| Dependency | Needed for | Notes |
|---|---|---|
| Python 3.10+ | backend | developed on 3.12 |
| Node.js 20+ | frontend | developed on 24 |
| A LaTeX compiler | PDF output | `latexmk`+`pdflatex`, `pdflatex`, `xelatex`, `lualatex` or `tectonic`; detected at runtime |
| `pdftotext` (Poppler) | PDF import and validation | optional; falls back to the bundled `pypdf` |
| Groq API key | AI suggestions | optional; everything else works without it |

macOS: `brew install python@3.12 tectonic poppler`
Debian/Ubuntu: `sudo apt install python3-venv texlive-latex-recommended texlive-latex-extra latexmk poppler-utils`

Without a LaTeX compiler the app still generates and exports the `.tex`; Settings shows what is
missing and how to install it. Tectonic downloads its packages on the first compile (needs
internet, took about five minutes here); later compiles take a few seconds and work offline.

## Run it

Backend (terminal 1):

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # optional: add GROQ_API_KEY
.venv/bin/python -m app       # http://127.0.0.1:8000
```

Frontend (terminal 2):

```bash
cd frontend
npm install
npm run dev                   # http://127.0.0.1:5173  (proxies /api to the backend)
```

Open http://127.0.0.1:5173. A fictional resume and job description to try are in
`backend/samples/`.

Single-process alternative: `npm run build` in `frontend/`, then the backend serves the built
UI itself at http://127.0.0.1:8000.

## Configuration

Everything is set through environment variables or `backend/.env` (see `backend/.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | empty | enables AI suggestions; never sent to the browser or written to logs |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | the one place the model is chosen |
| `GROQ_STRUCTURED_MODE` | `auto` | `strict`, `json_object`, or `auto` |
| `GROQ_TIMEOUT_SECONDS` / `GROQ_MAX_RETRIES` | 60 / 1 | retries apply to timeouts and 5xx only, never to 429 |
| `CVFORGE_HOST` / `CVFORGE_PORT` | `127.0.0.1` / `8000` | bind address |
| `CVFORGE_DATA_DIR` | `backend/data` | uploads, generated files, SQLite database |
| `CVFORGE_ACCESS_TOKEN` | empty | when set, every API call needs `Authorization: Bearer <token>` |
| `CVFORGE_MAX_UPLOAD_MB` | 5 | upload limit |
| `CVFORGE_COMPILE_TIMEOUT_SECONDS` | 300 | LaTeX compile timeout |
| `CVFORGE_IDLE_SHUTDOWN_MINUTES` | 0 | exit after this many minutes without requests (0 = never); see Nexus below |

### Model choice

Groq's documentation (checked October 2026) lists `openai/gpt-oss-120b` as a production model
that supports `response_format: json_schema` with `strict: true`, so it is the default and is
called in strict mode. Structured outputs cannot be combined with streaming or tool use; CV
Forge uses neither. For a model outside the known strict-capable set, `auto` switches to JSON
object mode with the schema in the prompt. In both modes the answer is re-validated with
Pydantic before use.

## Workflow

The UI groups the nine workflow stages into seven steps:

1. **Resume** – pick a saved master profile (or import one). The session snapshots it.
2. **Job description** – paste the posting.
3. **Requirements** – review, edit and re-match the extracted requirements and evidence.
4. **Tailor** – generate AI suggestions and accept, reject, edit or re-word each one.
5. **Configure** – section order, optional sections, skill priority, page limit, paper, font size.
6. **Generate** – build the `.tex`, compile the PDF, read the validation report.
7. **Export** – download `.tex`, PDF, match report (Markdown) and the full session record (JSON).

## How fabrication is prevented

- **The AI has a narrow target list.** It may rewrite the summary, bullets, and the order of a
  skills group. Employers, titles, dates, degrees, institutions, certifications and project
  names are not targets, so a suggestion aimed at them is rejected.
- **Evidence IDs are verified.** A suggestion with no evidence ID that exists in the master
  profile is rejected; unknown IDs are discarded and flagged.
- **Every wording is checked without AI.** New numbers, technologies or JD terms absent from the
  master resume, unfamiliar names, seniority wording, team-to-individual shifts, and phrases
  copied from the JD are flagged. Flagged wording needs an explicit confirmation tick, and the
  confirmation is recorded in the report. The same checks run on text you type yourself.
- **Nothing enters the draft unapproved.** Pending and rejected suggestions are never rendered.
  "Reset draft to master" returns every decision to pending.
- **Gaps stay gaps.** Unsupported requirements are reported as such and marked for the model as
  off-limits.
- **The PDF is checked against the draft.** After compiling, the extracted text is compared in
  both directions with what was approved, plus headings, contact details, dates, reading order
  and the source hash.

The match percentage is a labelled heuristic (the formula is shown in the UI). It is not an ATS
score, and the document checks cannot guarantee compatibility with every ATS.

## Privacy and security

- Binds to `127.0.0.1` by default. No analytics or telemetry.
- AI requests need a configured key **and** recorded consent (asked once, revocable in
  Settings). Requests contain job requirements and resume content (summary, skills, bullets and
  their job/education headings). Name, email, phone, location and links are not sent.
- Logs contain IDs, status codes and timings, never resume or JD text.
- Uploads: `.tex`/`.pdf` only, content-sniffed, size-limited, stored under a server-generated
  ID, written once read-only and never modified. Client file names are never used as paths.
- LaTeX: only the app's own template is compiled, with escaped data, shell escape disabled, a
  fixed argv, a private build directory, a minimal environment and a timeout.
- Delete any profile or session from the UI; optional automatic deletion of old sessions is in
  Settings. Master resumes are never deleted automatically.
- `.gitignore` excludes `.env`, the data directory and LaTeX artefacts. Only fictional sample
  data is in the repository.

## Tests

```bash
cd backend && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest -rs
```

Groq is mocked, so the suite needs no key or network. Tests that compile LaTeX are skipped
(and reported) when no compiler is installed. `tests/test_groq_integration.py` calls the real
API with the fictional sample and runs only when `GROQ_API_KEY` is set.

UI smoke tests drive the real frontend against a running backend:

```bash
cd frontend && CVFORGE_E2E_URL=http://127.0.0.1:8000 npm run test:ui
```

They create and delete their own sample profile and session; use a throwaway
`CVFORGE_DATA_DIR`. Without `CVFORGE_E2E_URL` they are skipped.

## Project layout

```
backend/app/
  config.py            environment-based settings
  models.py            profile, requirement, match, suggestion models; evidence index
  lexicon.py           skill vocabulary, aliases, related-term map
  parsing/             LaTeX parser, plain-text/PDF parser, shared heuristics
  jd/analyzer.py       rule-based requirement extraction
  matching/matcher.py  requirement-to-evidence matching and the heuristic score
  ai/provider.py       provider interface and error types
  ai/groq_client.py    Groq implementation
  ai/schemas.py        JSON schema + Pydantic models for AI output
  ai/validation.py     deterministic fact checks, draft assembly
  ai/tailoring.py      prompt construction and orchestration
  latex/               escaping, template, renderer, compiler/preflight
  ats/                 PDF validation, ATS report, Markdown match report
  storage/store.py     SQLite metadata + filesystem documents
  api/                 FastAPI routes
frontend/src/          React + TypeScript + Tailwind UI
```

To use another AI provider, implement `AIProvider` (`ai/provider.py`) and pass it to
`create_app`.

## Running on Nexus, on demand through Mission Control

On Nexus (the Termux phone) CV Forge is not kept running. It is a building in Mission Control's
village (the blacksmith's forge): cold and dark while stopped, fire and sparks while running.
"Open Dashboard" in Mission Control starts it, waits for it to answer, and opens it; after
`CVFORGE_IDLE_SHUTDOWN_MINUTES` (30 on Nexus) without requests it exits by itself.

```bash
# on Nexus, once
git clone git@github.com:jeevan221b/CV-Forge.git ~/Projects/CV-Forge
cd ~/Projects/CV-Forge && ./scripts/nexus-setup.sh   # deps, frontend build, backend/.env with a new token
# then redeploy Mission Control so it picks up the token and port
```

| Script | What it does |
|---|---|
| `scripts/nexus-setup.sh` | install/update deps, build the UI, write `backend/.env` (only if missing) |
| `scripts/nexus-start.sh` | start the `cv-forge` tmux session unless it is running (Mission Control calls this) |
| `scripts/nexus-stop.sh` | kill the session (Mission Control's "Shut down now") |
| `scripts/nexus-serve.sh` | the tmux entrypoint; log in `logs/cv-forge.log` |

How the pieces fit:

- **Idle shutdown.** Every request except `/api/health` counts as use, so Mission Control's
  health polling does not keep it alive. The UI sends `POST /api/keepalive` every two minutes
  while you are typing or clicking, so a long edit is not cut off; an untouched open tab sends
  nothing. `/api/health` reports the remaining time, which Mission Control shows.
- **Access.** It binds `0.0.0.0` with `CVFORGE_ACCESS_TOKEN` set. Mission Control's link carries
  the token as `#token=…`; the UI stores it like a typed-in token and removes it from the address
  bar (a URL fragment never reaches the server or its logs).
- **No wake lock.** Termux has one app-wide wake lock and Mission Control holds it; CV Forge
  never takes or releases it.
- **Not in the boot/cron watchdogs on purpose**: it is on demand.

## Known limitations

- LaTeX and PDF parsing are heuristic. Unusual macros and PDF layouts need manual correction in
  the profile editor; the parser reports what it guessed.
- JD extraction is rule-based and works best on postings with headings.
- The skill vocabulary (`lexicon.py`) is a fixed list; add terms there or as requirement
  keywords.
- The fact checks are conservative pattern checks, not proof. They cannot catch a false
  statement made entirely of words already in your resume.
- One built-in template. No authentication beyond the optional shared token.
