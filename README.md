# CSE Prep Master — Smart Exam Preparation Platform (Python/Django)

A full-stack web app for B.Tech CSE students: semester exams, placement
aptitude tests, technical interviews, competitive exams and coding
assessments.

## v3.0 — Django-only UI (current)

The Next.js frontend has been removed (it is in recoverable trash for 30
days if ever needed again). The app is now pure Django: server-rendered
pages, one server, no Node.js required.

- **Landing page:** light sidebar with grouped menus, top search bar,
  dark gradient hero ("CSE Prep Master" + "Start Practicing" / "Take a
  Mock Test" / "Coding Practice"), 4 feature cards, and Browse by
  category with per-subject cards.
- **Login/Register:** standalone glass pages (no sidebar), same
  Welcome-Back style as before. No social login — no OAuth exists.
- **All other pages** (dashboard, subjects, practice, mock tests,
  coding, mistakes, bookmarks, analytics, profile, contribute, review
  queue, assistant) keep their full functionality in the same light
  design system.
- The JSON API under `/api/` is still there (the Django pages use parts
  of it, e.g. practice answers and the study timer), but no separate
  frontend consumes it.

Run it (only Django needed):

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

Open http://127.0.0.1:8000/ — demo admin: admin@cseprep.local / admin123
(change it after first login via Django admin).

## v2.2 — Sales-Report dashboard + glass login (Next.js era)

- **Login (Welcome Back style):** glass card on soft blue, logo block,
  username/email + password with icons and a working show/hide eye,
  Remember Me that really remembers your email, gradient Login button,
  "OR CONTINUE WITH" Google/Discord/Facebook buttons, "PLAY • COMPETE •
  GROW TOGETHER" tagline. Register matches the same style.
- **Dashboard (Sales Report style):** light sidebar with grouped menus,
  top search that really searches courses, 4 stat cards with honest
  week-over-week changes, Study Habits monthly bar chart, Subject
  Statistics donut, Subject Reach bubbles, plus the v2.1 study tools
  (timer, coverage, tasks, calendar) restyled light below.
- **Honesty notes:** social buttons, Forgot Password?, and the bell show
  an honest "not connected yet" note — no OAuth, reset email, or
  notification system exists behind them. Dashboard accuracy now uses an
  exact `weekCorrect` count (not an estimate from rounded daily figures).
- **Backend:** dashboard payload gained `prevWeek`, `monthly` (6 months),
  and `weekCorrect`; 15/15 tests.
- **v2.2a fix (found while screenshotting):** the login/register pages
  were showing the sidebar because the full-bleed check compared against
  "/login" while the app serves "/login/" — fixed by normalizing the
  trailing slash in AppShell.

## v2.1 — UI/UX rebuilt like the reference dashboards

- **Dashboard (Crextio-style):** "Welcome in, [name]" greeting, big stat
  numbers, weekly progress bar chart, a **real study time tracker**
  (circular timer, start/pause, saves finished sessions), syllabus
  coverage card, tasks checklist, month calendar with your real study
  days highlighted, activity timeline, accuracy + subject charts.
- **My Courses (eCourse-style):** subjects as course cards with gradient
  covers, working Category/Level/Semester filters, per-subject progress,
  plus a calendar + top-contributors column.
- **Sidebar:** deep-purple eCourse-style sidebar.
- **Bug fixed:** `StudySession.started_at` used `auto_now_add`, which
  overwrote the timer's posted start time and made every saved session
  ~0 minutes. It is now a plain defaulted field (migration 0003) with a
  regression test.

## v2.0 — React + Next.js UI (removed in v3.0)

## Features

- **Subjects & syllabus** — Quantitative Aptitude, Logical Reasoning, Verbal
  Ability and Technical MCQs (DBMS, Networks, Web Development, OS,
  Pseudocode), with search by name/code, semester filter, and custom subjects.
- **MCQ practice** — subject/topic/difficulty filters, instant checking,
  green/red indicators, step-by-step explanations, retry, hints (topic
  revision notes) and bookmarks.
- **Timed tests & mocks** — configurable mode, question count, duration,
  marks and negative marking; question palette, mark-for-review,
  save-and-next, clear response, countdown with auto-submit. Answers and
  explanations are hidden until submission, and scoring happens on the
  server (never in the browser).
- **Coding practice** — 30 problems (easy/medium/hard) with statement, I/O
  format, constraints, examples, hints and complexity. Run with custom input
  or submit against sample + hidden tests. Hidden test inputs/outputs are
  never sent to the browser. Code runs in a child process with a 5-second
  timeout, capped output and temp-file cleanup (Python, JavaScript, C, C++;
  Java only when a JDK is installed on the host).
- **Dashboard & analytics** — attempted/correct/accuracy, accuracy by
  subject, topic and difficulty, recent mock scores, coding success rate,
  and recommendations computed from the student's real results.
- **My Mistakes** — wrong answers saved automatically with the original
  question, the student's answer, the correct answer, explanation, mistake
  count and retry/practice-all actions. Plus bookmarks.
- **Accounts** — register/login/logout, profile (semester, preferred
  subjects, goals). Guests can practice without an account; guest attempts
  and bookmarks are kept in browser localStorage.
- **Admin** — staff question-bank management at `/manage/` plus the full
  Django admin at `/admin/`.
- **Study Assistant** — topic-note search, formula explainer and a revision
  plan from real analytics. Works with no AI provider configured.
- **Dark/light themes, responsive layout** — works on desktop, tablet, mobile.

## What's new in v1.1

- **Dashboard like modern course/HR dashboards** — stat cards with accents,
  Chart.js charts (accuracy over the last 14 days, attempts by subject
  doughnut, weekly activity bars — Chart.js is vendored in
  `prep/static/prep/`, so charts work offline), a tasks checklist
  (mistakes to revise, bookmarks, mock test, coding) with progress, and a
  recent-activity feed.
- **Users can add questions + answers** — any logged-in student can submit
  a question with 4 options, the correct answer and a step-by-step
  explanation at `/contribute/`. Submissions wait in a review queue and
  enter practice/tests only after staff approval (`/manage/` queue);
  contributors track status at `/contribute/mine/`. Pending questions are
  never served by practice, tests or the public API.
- **Visual refresh** — softer cards with shadows, sticky pill-style nav,
  accent-colored stat cards, focus rings.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data      # imports data/seed_*.json + creates the admin user
python manage.py runserver
```

Open http://127.0.0.1:8000/

- Demo admin: **admin@cseprep.local / admin123** — change the password after
  first login (Django admin → Users).
- Re-running `seed_data` is safe (idempotent); it imports any new seed files.

## Deploying on Vercel (PostgreSQL)

The app is env-gated for production: locally nothing changes (SQLite, debug
on). On Vercel it runs with a real PostgreSQL database so accounts, attempts
and dashboard progress persist.

1. Import the GitHub repo in Vercel (framework: Django; `vercel.json` only
   raises the WSGI function timeout).
2. Add a Postgres database (Vercel Postgres / Neon) to the project — this
   provides `DATABASE_URL`. Settings read it via `dj-database-url` and switch
   from SQLite to PostgreSQL automatically; WhiteNoise serves static files
   when `DJANGO_DEBUG=0`.
3. Set environment variables in the Vercel project:
   - `DATABASE_URL` (from the Postgres store)
   - `DJANGO_SECRET_KEY` (long random string)
   - `DJANGO_DEBUG=0`
   - `DJANGO_ALLOWED_HOSTS=<your-vercel-domain>`
   - `DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-vercel-domain>`
4. One-time database setup against the production database:
   `python manage.py migrate && python manage.py seed_data`
   (run locally with `DATABASE_URL` pointing at the production database).

## Running tests

```bash
python manage.py test prep
```

Tests cover: scoring (+marks / −negative / unattempted), shuffled option
orders, the full test flow (create → answer → submit → review), review
blocking before submission, the code runner, and hidden-test protection.

## Project layout

```
cseprep/            Django project settings & root URLs
prep/               the app
  models.py         subjects, topics, questions, options, tests, attempts,
                    bookmarks, coding problems/submissions, sessions
  views.py          pages + JSON APIs (all scoring server-side)
  runner.py         sandboxed code execution
  templates/        server-rendered pages (no build step)
  static/prep/      one stylesheet, dark/light via CSS variables
  management/commands/seed_data.py
data/               seed banks (JSON): seed_apt.json, seed_tech.json,
                    seed_coding.json — edit these and re-run seed_data
db.sqlite3          created on first migrate (SQLite by default)
```

## API (JSON, session-authenticated where noted)

| Endpoint | Method | Notes |
|---|---|---|
| `/api/subjects/` | GET | subjects with topics, notes, question counts |
| `/api/questions/?subject=&topic=&difficulty=&search=&limit=` | GET | questions **without** answers |
| `/api/practice/answer/` | POST | `{question_id, selected}` → `{correct, correctOption, explanation}` |
| `/api/bookmarks/toggle/` | POST | login required |
| `/api/tests/<id>/answer/` | POST | save response / mark-for-review |
| `/api/tests/<id>/submit/` | POST | server-side scoring |
| `/api/coding/<id>/run/` | POST | `{code, language, input}` → `{output, error}` |
| `/api/coding/<id>/submit/` | POST | hidden tests returned as pass/fail only |

## Assumptions & honest limits

- **Database:** SQLite by default so the app runs anywhere with zero setup.
  The spec suggested PostgreSQL; the models use only standard Django ORM
  features, so switching is a `DATABASES` settings change plus `psycopg`.
- **Code execution:** process-level sandbox (timeout, output cap, temp dir).
  This is fine for a single-user/local deployment; it is **not** a hardened
  multi-tenant judge — for public multi-user hosting, run the judge in an
  isolated container/VM.
- **Java:** not available unless a JDK is installed on the host; the UI says
  so instead of pretending.
- **AI Study Assistant:** intentionally local (notes + analytics). No API
  keys are needed or stored anywhere; adding an LLM provider later is a
  backend-only change.
- **Subject codes** differ by university, so the seeded codes (e.g. CSE-301)
  are illustrative internal codes, not a claim about any university's
  syllabus. Admins can edit/add subjects freely.
- **Questions are original practice questions**, not official previous-year
  papers; nothing in the bank claims verified PYQ provenance.
- **Guest progress** lives in browser localStorage and is not merged into an
  account automatically; logging in before practicing keeps everything in
  one place.
