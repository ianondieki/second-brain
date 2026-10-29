# Section 10 — Project reminders (email + WhatsApp)

A **LangGraph** workflow that looks at the project folders on this laptop every
morning, sends an **investigator agent** into each one that has gone cold, and
reminds you by **email** (full digest) and **WhatsApp** (one short nudge). Runs
from a small Python virtual environment via Windows Task Scheduler. No Docker, no n8n.

```text
Task Scheduler (08:00-23:00 every 30 min, at log-on, catches up after sleep)
   └─ .venv\Scripts\pythonw -m reminder            (reminder/graph.py)

   START ─▶ scan ─┬─ nothing flagged ─▶ record_nothing ─▶ END
                  └─▶ investigate ─▶ compose ─▶ deliver ─▶ END

   scan         every sub-folder of projects_roots: files, git state, README TODOs;
                cold = no work for 3 days, at risk = uncommitted / unpushed work   (code)
   investigate  one agent per flagged project (up to max_investigate):
                  model ⇄ tools loop  ─▶  structured verdict
                  tools: list_files · read_file · search_files · git_summary  (read-only,
                  locked to that folder, secrets refused/redacted)
                  verdict: unfinished | probably_done | not_a_project | unclear,
                           where you left off, next 15-minute step, confidence, evidence
   compose      email digest + WhatsApp variables from the verdicts                (code)
   deliver      once per channel per day, retries, alert on give-up               (code)
```

**Division of labour.** The agent decides *what to say* and whether a folder is
really unfinished. Plain code decides *whether and when to send*: the once-a-day
rule, the retry budget, the WhatsApp template and the email layout. So a confused
or manipulated agent can, at worst, word a reminder badly; it can never send twice,
spam you, or write to a project. If the model is down, out of quota or returns
junk, the run falls back to plain wording built from the scan and still goes out.

Framework: [LangGraph](https://github.com/langchain-ai/langgraph) 1.x with
`langchain-groq` (the same stack as `personal-assistant/`). The agent loop is the
canonical `StateGraph` + `ToolNode` pattern, so swapping the model provider means
changing `make_llm()` in `reminder/graph.py` only.

## What the two messages look like

Both are written for someone who has never seen the code: short sentences, everyday words,
one clearly marked action per project, and every technical word (git, commit, push)
explained once.

**Email** (full digest). The plain-text part and the HTML part have the same parts in the
same order:

| Part | What it tells you |
|---|---|
| **At a glance** | one sentence ("2 projects need you today"), what "the assistant" is, and four counts: need you, maybe finished, maybe not projects, going fine |
| **Heads-up** | only when the reminder itself needs you, for example a new WhatsApp template Meta rejected (see *Changing the WhatsApp wording*) |
| **Projects that need you** | one card per project, most urgent first and numbered: how long it has been quiet, a red **Work at risk** box that says what could be lost, *where you left off*, and a highlighted **Your next step (about 15 minutes)** box |
| **Maybe finished** | the assistant thinks the work is done. The card says how sure it is and shows the exact edit for `"done"` in `reminders.json` |
| **Maybe not a project** | the same for folders that look like downloads or course files, with the edit for `"ignore"` |
| **Everything else** | projects going fine, projects you marked done or snoozed, folders that were skipped (backup copies are grouped into one line) |
| **How this works** | when a project gets listed, what git, commit and push mean, and where the settings file is |

Each card ends with a small **More details** list (clues the assistant checked, recent
commits, changed files, open to-do items, the folder). A card the assistant did not look
inside says "Quick check only". The subject line names the projects and the day, so each
day's email is its own conversation in Gmail:
`2 projects need you today: soc-agents (work at risk), personal-assistant (no work for 60 days) · Mon 21 Sep`.

**WhatsApp** (one project a day). WhatsApp shows the header in bold and the footer in small
grey type; `*asterisks*` make the labels bold:

```text
Daily project update                                    <- header (bold)

Here is today's update on one of your projects.

📌 *Today's project:* soc-agents
⏳ *Why it is on the list:* work at risk: 2 changed files not committed for 5 days; no work for 5 days

📝 *Where you left off:*
Last commit: "phase 3: weather agent".

👉 *Your next step (about 15 minutes):*
Look over your changes in router.py and agents/weather.py, then commit them.

Today's email lists every project that needs you, with more details.

Sent by your Second Brain                               <- footer (small, grey)
```

The four filled-in parts are cleaned before sending: no line breaks, at most 180
characters each, and WhatsApp's own formatting marks (`*`, `~`, a backtick, and an `_` at
the edge of a word such as `__init__.py`) are swapped for look-alike characters. Without
that, one stray `*` in a commit message would pair with a label's bold and garble the
message. An `_` inside a word, as in `test_remind.py`, is left alone because WhatsApp never
treats it as a mark.

`python -m reminder --dry-run` prints both messages (and writes the HTML to
`.state\preview.html`) without sending anything.

## What counts as "gone cold"

| Signal | Rule (defaults in `reminders.json`) |
|---|---|
| **Cold** | no edited files and no commits for `cold_after_days` (3) |
| **At risk: uncommitted** | tracked files changed but not committed, untouched for `at_risk_after_days` (3) |
| **At risk: unpushed** | local commits not on `origin`, made `at_risk_after_days` or more ago |

- Files a running app writes (`.db`, `.log`, `.env`, `__pycache__`, `node_modules`, `.venv`,
  anything in the project's `.gitignore`) don't count as work.
- Backup copies such as `soc-agents_backup_2026-09-15` are skipped when `soc-agents` exists.
- Git state is read straight from `.git` (no git needed) and was checked against
  `git status` / `git rev-list @{u}..HEAD`, including Windows line endings.
- Working on a project resets its clock automatically. There are no commands to remember.

## Settings: `reminders.json`

Created from `reminders.example.json` on first run; not committed to git.

```json
{
  "projects_roots": ["C:/Users/PC/Desktop/second-brain"],
  "cold_after_days": 3,
  "at_risk_after_days": 3,
  "send_after_hour": 8,
  "max_investigate": 4,
  "ignore": ["multi-agents"],
  "track": [],
  "done": ["portfolio"],
  "snooze": {"personal-assistant": "2026-10-01"},
  "notes": {"soc-agents": "waiting on demo feedback"}
}
```

- **done**: never remind about these folders again.
- **snooze**: pause until a date; reminders resume *on* that date.
- **ignore**: folders that aren't projects. **track**: force-include a folder that
  would be ignored or treated as a backup copy.
- **notes**: extra context the agent reads before suggesting a next step.
- **max_investigate**: how many flagged projects the agent inspects per run (the rest
  get plain wording). Each takes roughly a minute on Groq's free tier because calls
  are paced to its 8,000-tokens-per-minute limit.

The email also carries the agent's hints: a project it judges **probably finished**
or **not a project** is listed separately with the exact line to add to `done` or
`ignore`, and is never the WhatsApp pick.

Changes apply on the next run; nothing to restart.

## Secrets: `.env`

| Key | What |
|---|---|
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | Gmail account + [App Password](https://myaccount.google.com/apppasswords) (needs 2-Step Verification) |
| `REMINDER_EMAIL_TO` | where the email goes (defaults to `GMAIL_ADDRESS`) |
| `WA_ACCESS_TOKEN` | Meta System User token |
| `WA_PHONE_NUMBER_ID`, `WA_BUSINESS_ACCOUNT_ID` | from WhatsApp → API Setup |
| `WA_TARGET_NUMBER` | your number, e.g. `2547XXXXXXXX` |
| `WA_TEMPLATE_NAME` | template to send. May list several, best first: `project_checkin_v2,project_checkin` (see *Changing the WhatsApp wording* below) |
| `WA_TEMPLATE_LANG` | `en` |
| `WA_GRAPH_VERSION` | optional, defaults to `v26.0` |
| `GROQ_API_KEY`, `GROQ_MODEL` | the agent's model (`openai/gpt-oss-20b`); without a key the agent is skipped |

Either channel works alone: fill only the Gmail keys for email-only reminders.

## Setup

### 0. Python environment (once)
```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt   # langgraph, langchain-groq
.venv\Scripts\python.exe -m reminder --dry-run                 # watch the agent work; sends nothing
```

### 1. Email (5 minutes)
1. Turn on 2-Step Verification for the sending Gmail account.
2. Create an App Password at <https://myaccount.google.com/apppasswords>.
3. Fill `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` (and `REMINDER_EMAIL_TO` if different).
4. Test: `python -m reminder --force --channel email`

### 2. WhatsApp via Meta Cloud API (about 20 minutes, plus template approval)
1. <https://developers.facebook.com/apps> → **Create App** → use case
   **"Connect with customers through WhatsApp"** → pick/create a business portfolio.
2. **Start using the API** → **WhatsApp → API Setup**. Meta creates a free test number.
   Copy the **Phone Number ID** and **WhatsApp Business account ID**.
3. Add your own number in the **To** field and confirm the code WhatsApp sends you
   (a test number can message up to 5 verified numbers).
4. Permanent token: <https://business.facebook.com/latest/settings> → **System users** →
   **Add** (Admin) → **Assign assets**: the app and the WhatsApp account, full control →
   **Generate token** with `whatsapp_business_messaging`, `whatsapp_business_management`,
   `business_management`; choose the longest expiry offered.
5. Fill `WA_ACCESS_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_BUSINESS_ACCOUNT_ID` in `.env`.
6. Check the plumbing: `python -m reminder --whatsapp-hello` (you should get Meta's hello_world).
7. Submit the reminder template: `python -m reminder --whatsapp-create-template`
8. Wait for approval (can take up to 24 h): `python -m reminder --whatsapp-template-status`
9. Test: `python -m reminder --force --channel whatsapp`

The template lives in `reminder/notify.py` (`TEMPLATE_HEADER`, `TEMPLATE_BODY`,
`TEMPLATE_FOOTER`); the layout is shown under *What the two messages look like* above.
Meta's rules that the tests check for you: the body may not start or end with a variable,
two variables may not sit next to each other, the header has no formatting marks, the
bold marks stay on the fixed label text (never around a variable), the filled-in body
stays under 1024 characters, and a new template's wording differs from the first one
(Meta rejects a template that repeats an existing one's wording).

#### Changing the WhatsApp wording

Meta reviews every change to a template. Its docs do not say whether an approved template
can still be sent while an edit of it is being reviewed, and an approved template may only
be edited once in 24 hours. So don't edit the live one. Create the new wording under a
**new name** and let the old one keep working until Meta approves the new one:

1. Edit the template text in `reminder/notify.py` (keep the four variables).
2. Put the new name **first** in `.env`, keeping the live one after it:
   `WA_TEMPLATE_NAME=project_checkin_v2,project_checkin`
3. `python -m reminder --whatsapp-create-template` submits the **first** name. If Meta files
   it as MARKETING instead of UTILITY, the command says so: don't use that template (marketing
   messages cost more and Meta limits how many a person gets). Reword it as a plain status
   update and submit it under another new name.
4. `python -m reminder --whatsapp-template-status` shows every name in the list and which
   one reminders will go out with today.

Nothing else to do. Every send tries the first name; while Meta answers "no approved
template with that name" (error 132001), or the template is paused (132015) or disabled
(132016), the same message goes out with the next name instead, and the log says so. The
day Meta approves the new template, the reminders switch to it by themselves. Once it is
live you can shorten the list to just the new name.

A fallback is never silent for long. After one, the reminder asks Meta why the newer
template was refused and keeps a note. The next email opens with a **Heads-up** when you
have to act: Meta rejected, paused or disabled it, no template has that name, or it exists
in another language than `WA_TEMPLATE_LANG`. A template that is simply still in review is
only mentioned once the review has taken two days or more. A failure that may fix itself
(no network, Meta's servers busy) never moves on to the next name, because Meta may already
have accepted the first message.

### 3. Schedule it
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-reminder-task.ps1
```
Remove with `scripts\uninstall-reminder-task.ps1`.

## Everyday commands

```powershell
.venv\Scripts\python.exe -m reminder --dry-run          # agent verdicts, tool calls, both messages; sends nothing
.venv\Scripts\python.exe -m reminder --dry-run --verbose  # plus per-step timings and pacing waits
.venv\Scripts\python.exe -m reminder --force            # send now, even if already sent today
.venv\Scripts\python.exe -m reminder --no-llm --dry-run # plain wording, agent skipped
.venv\Scripts\python.exe -m unittest discover -s tests -t .   # run the test suite
```

## How it behaves
- Nothing happens before `send_after_hour`. After that, each channel sends **once per day**.
- If the laptop was asleep at 08:00, the task runs when it wakes (and 3 minutes after log-on).
- A failed channel retries on later runs. Failures that need you (bad token, template not
  approved, wrong recipient) count toward **3 attempts a day**, then it gives up and you get one
  alert email. Network failures don't count: it just keeps trying every half hour that day.
  `--force` never re-arms a channel that already sent or gave up. Everything is logged to
  `.state\remind.log`.
- If nothing is cold, nothing is sent. If the agent judges every cold folder finished or not a
  project, the email still goes (with the `done`/`ignore` hints) and WhatsApp stays quiet.
- If Groq is down or out of quota, the reminder still goes out with plain wording.
- WhatsApp shows one project per day and rotates, so it doesn't repeat the same nudge.
- With several names in `WA_TEMPLATE_NAME`, a template Meta cannot use yet is skipped and the
  next one carries the same message. That is one attempt, not several: the retry budget only
  moves when every name in the list fails.
- If a channel gives up for the day, the alert email says what happened, then how to fix it
  (with the command to run, for the known cases: expired token, number not allowed, template
  not approved, paused or disabled, no payment method), and only then the technical details.

## What the agent can and cannot do
- Read-only tools on the flagged project's folder only; paths that resolve outside it are
  refused, including through symlinks and Windows directory junctions, and files with extra
  hard links are refused. `.env*`, key/certificate files, and binaries are refused; secrets in
  text (`KEY=`, JSON `"api_key":`, `user:pass@` in URLs, `Authorization:` headers, PEM key
  blocks) are redacted before the model sees them.
- At most 6 tool calls per project, each result capped at 4,000 characters; calls are paced to
  the free-tier token limit instead of hitting it, and the whole agent phase stops after 15
  minutes (later projects get plain wording) so a run always finishes inside the scheduler's
  25-minute limit.
- If the scan itself fails (for example a projects root on a disconnected drive), the run
  reports the error and sends nothing; it does not mark the day as done.
- Its output is validated against a fixed schema (status enum, 0-1 confidence, ≤3 evidence
  items) and then clipped and cleaned before it reaches the WhatsApp template or the email.
- Text inside your projects is untrusted input to the model. A file that says "ignore your
  instructions" can at most make that project's wording odd. Nothing the agent reads can
  trigger a send, a config change or a write.

## Known limits
- **"Accepted" isn't "delivered".** Without a webhook, a WhatsApp message Meta accepts but
  later fails to deliver (e.g. error 131026) goes unnoticed. The email is the reliable record.
- **Template category.** Meta may file the template as MARKETING instead of UTILITY; it
  still works but costs more on a real number. `--whatsapp-template-status` tells you.
- **Pricing changes on 2026-10-01.** Meta starts charging for more message types. Test
  numbers don't need a payment method today; whether that changes for them isn't documented.
  If WhatsApp sends start failing with a payment error (131042), add a payment method.
- **Antivirus TLS scanning.** Avast re-signs HTTPS on this laptop. The script keeps full
  certificate checks but relaxes Python 3.13's extra strictness, and uses Gmail port 587
  (Avast deliberately breaks 465). See `tls_context()` in `reminder/notify.py`.
- The laptop has to be on at some point during the day; the reminder runs locally.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No delivery channel is configured` in the log | Fill the Gmail and/or `WA_*` keys in `.env` |
| `Gmail rejected the login` | Use an App Password, not your normal password |
| `WhatsApp API HTTP 401, code 190` | Token expired or revoked: generate a new System User token |
| `code 131030` | Your number isn't added/verified as a recipient on the test number |
| `code 132001` | Template not approved yet, or `WA_TEMPLATE_LANG` differs from the template's language. Check with `--whatsapp-template-status`; keep an approved name later in `WA_TEMPLATE_NAME` so reminders still go out meanwhile |
| `CERTIFICATE_VERIFY_FAILED` | Another TLS-scanning product: check `.state\remind.log` for the issuer |
| Nothing arrives, no errors | `python -m reminder --dry-run`: maybe nothing is cold, or the project is done/snoozed |
| Task not running | Task Scheduler → *SecondBrain Project Reminder* → History / Last Run Result |
