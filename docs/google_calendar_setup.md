# WF2 Google Calendar integration — setup checklist

One-time setup for the current interactive WF2 backend: after human approval, a scheduling
mutation is stored locally and synchronised through the Google Calendar API to a dedicated
project account. The code fallback is `mock` when no local setting is present, and formal
evaluation always injects that mock explicitly (`docs/workflow_design.md`).

**Before you start — two ground rules that keep this low-risk:**
- Use a **brand-new Google account created only for this project.** Never your real/daily one:
  screenshots and the viva recording would otherwise show your real identity/contacts/events.
- We never add anyone as an *attendee*, so Google never emails anyone. You don't need — and
  must not use — any real person's email anywhere below.

---

## Step 1 — Create a dedicated project Google account
accounts.google.com → create account → keep the login somewhere safe. Nothing else installed
on it.

## Step 2 — Google Cloud Console (console.cloud.google.com), signed in as that account
1. Top bar → **New Project** (any name, e.g. `wf2-demo`). Select it.
2. **APIs & Services → Library** → search **Google Calendar API** → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type: **External** → Create.
   - App name `wf2-demo`, your throwaway email as support + developer contact → Save.
   - **Audience / Test users → Add users →** add **only that same throwaway email** → Save.
   - Leave publishing status as **Testing** (do not "Publish").
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Desktop app** → Create.
   - **Download JSON.** Save it in the repo as **`secrets/client_secret.json`**
     (exact name; it's gitignored).

## Step 3 — Create the demo people's calendars
In that account's Google **Calendar** UI (calendar.google.com):
- Left sidebar → **Other calendars → + → Create new calendar**. Make e.g. **`Bob Rivera (demo)`**
  and **`Chen Wei (project)`** → Create.
- For each: hover it → ⋮ → **Settings** → scroll to **Integrate calendar** → copy the
  **Calendar ID** (looks like `...@group.calendar.google.com`).
- Copy `secrets/google_calendars.json.example` to **`secrets/google_calendars.json`** and paste
  the IDs, keyed by the person id used in the app (`bob`, `chen`, …):
  ```json
  { "bob": "....@group.calendar.google.com", "chen": "....@group.calendar.google.com" }
  ```
  (Any person not listed here is simply skipped when booking — no error.)

## Step 4 — Authorise (one browser click; cached afterwards)
```
uv pip install --python .venv/bin/python google-api-python-client google-auth-oauthlib   # already installed, skip if so
PYTHONPATH=. .venv/bin/python -m backend.scripts.google_auth_setup
```
A browser opens → pick the throwaway account → you'll see an **"unverified app" warning**
(expected for Testing mode) → **Advanced → go to wf2-demo (unsafe) → Allow**. It caches the
token to `secrets/google_token.json` and prints the next hint.

> The token expires after **7 days** (Google's unverified-app limit). When a booking later
> reports "token expired", just re-run this one command. The UI/error message will say so.

## Step 5 — Select the current interactive backend
Add to `.env` (repo root, gitignored):
```
CALENDAR_BACKEND=google
```
The current local `.env` already uses this setting. Restart the backend after changing it,
then book the flagship scenario
("Set up a 1 hour Q3 budget review with Bob and Chen next Tuesday at 14:00 in Orion" →
Extract → Book). The result panel should show **"View in Google Calendar"**, and the event
appears on the `Bob`/`Chen` project calendars. To go back to offline: remove that line (or set
`=mock`) and restart.

---

## Also do (not a code step): document authorisation
A one-line written approval is enough, e.g.:

> "Confirming I may connect WF2 to a real Google Calendar for a feasibility demo, using only
> a dedicated test account I created, with no real individuals' emails or calendars involved."

Keep the written approval with the project records. The code already enforces the safeguards;
the approval documents that the human sign-off was real.

## If something goes wrong
- **"missing credential file"** → a `secrets/…` file is absent or misnamed. Check Step 2.4 / 3.
- **"unverified app" screen** → expected; Advanced → proceed.
- **booking says "Google Calendar sync failed"** but the meeting still books locally → that's
  the non-blocking design working. Re-auth (Step 4) if it mentions the token; the local record
  and `.ics` are unaffected.
- **evaluation numbers** never touch any of this — the eval harness always runs on mock.
