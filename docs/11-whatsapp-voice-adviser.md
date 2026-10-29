# Section 11 — WhatsApp voice adviser (two-way)

The daily reminder only *talks to you*. The adviser lets you **talk back**: reply on
WhatsApp by **text or voice note**, and your second brain answers like a senior
developer who knows every project on this laptop. Send a voice note and you get a
**voice note back**, fluent and natural, like a call. Type and you get text.

Things you can say (or type):

- "Tell me more about today's project." (reply to the morning reminder)
- "Expound on soc-agents. What is it, how far along is it, what's the risk?"
- "Where did I leave off on personal-assistant?"
- "What should I work on today?"
- "I finished portfolio." → it asks *"Shall I stop reminding you about portfolio? Say yes or no."*
- "Give me a week off soc-agents." → it asks before pausing the reminders.

```text
you (WhatsApp) ──▶ Meta ──HTTPS──▶ Cloudflare tunnel ──▶ this laptop, 127.0.0.1:8765
                                                          .venv\Scripts\pythonw -m adviser serve

  acknowledge  blue ticks + "typing…" at once
  hear         voice note ─▶ Groq Whisper (speech-to-text), helped with your project names
  route        /commands and your yes/no to a reminder change, decided in plain code
  think        the adviser agent: model ⇄ read-only tools over ANY project folder
                 tools: list_project_files · read_project_file · search_project ·
                        project_git · propose_reminder_change (asks you first)
                 knows: a fresh scan of every project + what today's reminder said +
                        your conversation so far (last 6 exchanges; starts fresh after
                        6 quiet hours or a new reminder)
  speak        edge-tts (Microsoft neural voices) ─▶ OGG/Opus voice notes; the first
               sentence or two is sent within seconds while the rest is still being made
  deliver      voice notes (+ anything better read than heard, like a command, as text)
```

**Safety, in plain words.**
- Every message from Meta carries a signature made with your **App Secret**. The
  adviser checks it and drops anything unsigned. It answers **only your number**
  (`WA_TARGET_NUMBER`); a stranger gets silence and costs you nothing.
- The agent can **read** your projects (secret files like `.env` and keys are
  refused, and passwords in code are blanked out). It **cannot** edit code, run
  commands, commit or push.
- The only thing it can change is `reminders.json` (done / pause / back on the list),
  and only after **you** answer a fixed question ("Shall I stop reminding you about
  portfolio? Say yes or no.") with a plain yes. The yes is checked by plain code, not by
  the model. Anything mixed ("ok, no thanks", "yes, not yet") gets the question again.
  The old file is kept in `.state\reminders.json.bak`. If the model ever *claims* it
  changed a reminder, that sentence is removed before you see it.
- If the laptop or the adviser stops in the middle of an answer, your message is kept on
  disk and answered when it starts again (if it is less than 23 hours old).
- The server only listens on `127.0.0.1`; the internet reaches it only through the
  tunnel, and only the `/webhook` and `/health` addresses answer.

## One-time setup (about 5 minutes)

Everything the reminder uses (`WA_ACCESS_TOKEN`, `WA_PHONE_NUMBER_ID`,
`WA_BUSINESS_ACCOUNT_ID`, `WA_TARGET_NUMBER`, `GROQ_API_KEY`) is reused. You add
**one** value.

1. **Copy your App Secret into `.env`.**
   Meta App Dashboard → your app (*n8n personal assistant*) → **App settings → Basic**
   → **App secret** → **Show** (Meta may ask for your password first). Add a line:

   ```ini
   WA_APP_SECRET=paste-it-here
   ```

2. **Check.** Nothing is sent or changed:

   ```powershell
   .venv\Scripts\python.exe -m adviser check
   ```

   Every line should be ticked. `cloudflared.exe` lives in `tools\` (it is
   git-ignored; download it from Cloudflare's GitHub releases if it is missing).

3. **Start it and watch the first run.**

   ```powershell
   .venv\Scripts\python.exe -m adviser serve
   ```

   Within about 10-30 seconds you should see:

   ```text
   Tunnel up at https://<random-words>.trycloudflare.com; waiting for it to connect...
   Meta verified the webhook.
   Webhook registered with Meta: https://<random-words>.trycloudflare.com/webhook
   ```

   A brand-new address can take a minute to become known on the internet, so a line
   like `Meta could not verify ... yet; retrying in 15s` before the last one is normal.

   The adviser **registers its own address with Meta** (it is a new address every
   time cloudflared starts, so it does this on every start). You never paste URLs
   into the dashboard.

4. **Say hi.** From your WhatsApp (the number in `WA_TARGET_NUMBER`), send
   "hi" to the business test number, the one the reminders come from. Then send a
   voice note: *"Where did I leave off on personal-assistant?"*

5. **Run it in the background, always.**

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install-adviser-task.ps1 -StartNow
   ```

   Task Scheduler starts it at log-on and checks every 15 minutes that it is still
   running. Remove it with `scripts\uninstall-adviser-task.ps1`.

**If step 3 says "Meta refused … subscriptions".** The automatic registration needs the
App Secret to be right. If it still fails, do it by hand once: App Dashboard →
**WhatsApp → Configuration → Webhook → Edit**. For **Callback URL**, paste the address
from `.state\adviser\public_url.txt`. For **Verify token**, paste the text in
`.state\adviser\verify_token.txt`. Then **Verify and save**, and under **Webhook fields**
subscribe to **messages**. (The address changes when the adviser restarts, so fix the
automatic registration when you can.)

## Everyday use

| Send | What happens |
|---|---|
| a voice note | a voice note back (Swahili voice notes get a Swahili voice) |
| text | text back; add "send a voice note" to hear it instead |
| `/voice` | always answer with voice notes, even to text (a "call mode") |
| `/text` | always answer in text |
| `/auto` | back to the default: voice for voice, text for text |
| `/projects` | every project and its state, from a fresh scan |
| `/reset` | forget the conversation and start fresh |
| `/help` | the list above |

Try it without WhatsApp, in the terminal (same brain, same tools, separate memory):

```powershell
.venv\Scripts\python.exe -m adviser chat               # type questions; answers as text
.venv\Scripts\python.exe -m adviser chat --voice       # answers saved as .ogg files in .state\adviser\console
.venv\Scripts\python.exe -m adviser say "Hello Ian"    # just the voice, into .state\adviser\say.ogg
.venv\Scripts\python.exe -m adviser hear some.ogg      # just the speech-to-text
```

Settings (all optional, in `.env`): `ADVISER_REPLY_MODE` (mirror | voice | text),
`ADVISER_VOICE` (default `en-US-AndrewMultilingualNeural`; Kenyan English:
`en-KE-ChilembaNeural` or `en-KE-AsiliaNeural`), `ADVISER_VOICE_SW`,
`ADVISER_VOICE_RATE` (e.g. `+10%`), `ADVISER_MODELS` (Groq models to rotate through).

## The daily check-in, spoken

The daily reminder still sends the email and one approved WhatsApp template. WhatsApp does not
allow a business to start a conversation with audio: a template can carry text, an image, a
video or a document, never a voice note, and free-form messages (voice notes among them) are
only allowed inside the **24-hour customer service window**, which opens whenever you write to
the number. So the adviser speaks the check-in as soon as it is allowed:

| When the reminder goes out | What you get |
|---|---|
| you wrote to the adviser in the last 24 hours | the voice note arrives within a minute of the reminder |
| you did not | nothing yet; it is spoken the moment you next write, alongside the answer to that message |
| the check-in is more than 14 hours old | it is dropped, so you never hear yesterday's news |
| nothing needs work, or you set `/text` | not spoken at all |

It is spoken **once per reminder**. The words come only from what the reminder itself sent
), so the voice cannot invent a project or a next step; it names the two
most urgent projects in full and counts the rest. (That file is `.state\briefing.json`.)

```powershell
.venv\Scripts\python.exe -m adviser brief --dry-run   # print what would be said, send nothing
.venv\Scripts\python.exe -m adviser brief             # say it now, if WhatsApp allows it
```

Switch it off with `ADVISER_DAILY_VOICE=off` in `.env`.

**Cost.** Today both the reminder template and the voice note are free: Meta does not charge for
messages inside an open window. From **1 October 2026** Meta starts charging for service messages
and for utility templates sent inside an open window, so from that date the spoken check-in is a
paid message.

## How long a reply takes (measured on this laptop)

| | first voice note | whole answer |
|---|---|---|
| follow-up question (no files to read) | about 4-5 s | about 10-20 s |
| question that needs a README or code file | about 10-15 s | about 15-25 s |

The model answers in 1.5-6 s (Groq). Most of the rest is making the speech, which
depends on your internet speed: edge-tts downloads the audio at roughly one to two
times real time here. So the first note is kept to a sentence or two and made on its
own, with the full connection, then sent at once. The next notes are made in parallel
while you listen. Commands and code never go into a voice note; they come as a
separate text in monospace.

## Limits worth knowing

- **You start, it replies.** WhatsApp only lets a business send free-form messages
  within 24 hours of *your* last message. The adviser only ever replies, so this never
  bites. (The morning reminder uses an approved template for the same reason.)
- **Not a live phone call.** Replies are voice notes, not a real-time call.
  WhatsApp's Calling API needs WebRTC audio streaming, which is a different, much
  bigger build.
- **Free tiers.** Groq Whisper: 20 voice notes a minute, 2,000 a day. The models:
  about 8,000 tokens a minute *each*, so the adviser rotates to the next model when one
  runs out (you will see `gpt-oss-20b` in the log sometimes). If all are busy, you get
  "my thinking engine is overloaded, give me a minute" instead of silence.
- **Who hears what.** Project file excerpts go to Groq (as with the daily reminder's
  investigator); voice notes go to Groq for transcription; reply text goes to
  Microsoft's speech service (edge-tts, the voices behind Edge's Read Aloud). edge-tts
  is unofficial: if Microsoft changes it, replies fall back to text until
  `pip install -U "edge-tts<8"`.
- **The laptop must be on.** Asleep = no replies. When it wakes, the tunnel
  reconnects by itself, or restarts and registers its new address.
- **Why Cloudflare and not ngrok:** Avast re-signs ngrok's connection and ngrok
  refuses it (checked 2026-09-22). Cloudflare's tunnel runs over QUIC, which Avast leaves
  alone.

## Troubleshooting

Everything is logged to `.state\adviser.log`.

| You see | Meaning | Fix |
|---|---|---|
| no reply, and the log shows nothing | Meta is not delivering to the adviser | Is it running? `check`, then `serve` in a console and read the output. |
| `Rejected a webhook POST with a missing or wrong signature` | `WA_APP_SECRET` is wrong | Copy it again from App settings → Basic. |
| `Ignored message … not the owner` | the message came from another number | Only `WA_TARGET_NUMBER` gets answers (by design). |
| `Meta could not verify ... yet` / `Meta refused … subscriptions … code 2200` | Meta could not reach the new address yet | Normal for about a minute; it retries every 15 s, then starts a fresh tunnel. If it never works, see "If step 3 says…" above. |
| `Meta refused … code 190` or `code 100` | the App Secret, app or token is wrong | Check `WA_APP_SECRET` (and `WA_APP_ID` if you set it). |
| `Port 8765 is busy` | the adviser is already running | That's fine: the background task is up. |
| a reply comes as text instead of voice | speech failed (network, edge-tts changed) | The log says why; the text is the same answer. |
| "my thinking engine is overloaded" | all Groq models are over their per-minute budget | Wait a minute. |
| `cloudflared stopped` / `never connected` / `lost its connection` | tunnel trouble (network, sleep) | It starts a new tunnel and registers it again, with a growing pause (15 s to 5 min). |
| "Sorry, I need a clear yes or no" | your answer to a reminder change mixed yes and no ("ok, no thanks") | Answer just "yes" or "no". Nothing changes until a clear yes. |
| "something went wrong on my side (…)" | a real error, not a busy model | The log has the details. |
| replies sometimes take 30 s longer, or a voice note also arrives as text | a local connection on the laptop stalled (seen with Avast's filtering while the laptop was busy) | Nothing is lost: it falls back to text. If it happens often, add the second-brain folder (`python.exe`, `pythonw.exe`, `tools\cloudflared.exe`) to Avast's exceptions. |

Tests (no network, nothing sent): `.venv\Scripts\python.exe -m unittest discover -s tests -t .`
