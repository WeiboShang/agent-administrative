"""One-time Google Calendar OAuth setup for the WF2 interactive integration (design §18).

Run once (and roughly weekly thereafter — unverified-app refresh tokens expire after 7 days
in OAuth "Testing" mode). Caches the token to secrets/google_token.json.

    uv pip install --python .venv/bin/python \\
        google-api-python-client google-auth-oauthlib      # first time only
    PYTHONPATH=. .venv/bin/python -m backend.scripts.google_auth_setup

Uses a **manual copy-paste flow** rather than a local-callback server, because this project
runs under WSL: the callback server would live in WSL while the browser is a Windows browser,
so the browser cannot reach `http://localhost:<port>` inside WSL (ERR_CONNECTION_REFUSED).
The manual flow never needs that connection — you paste the redirected URL back in yourself.

Scope is the narrowest that covers events().insert(): calendar.events only — NOT full
calendar, NOT Gmail/Drive. Nothing here touches the evaluated core.
"""
import os

from .. import config

# events-only: create/read/update/delete events on calendars the account owns. Deliberately
# not calendar.readonly (can't write) or the broad calendar scope (more than we need).
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# The loopback redirect is only ever hit by the user's own browser on their own machine; the
# code is copied back by hand and exchanged over Google's HTTPS token endpoint. oauthlib
# refuses a plain-http redirect target by default, so allow it for this localhost-only flow.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

REDIRECT_URI = "http://localhost"   # Desktop clients auto-allow any localhost redirect


def main() -> None:  # pragma: no cover — interactive, needs a real browser + credentials
    from google_auth_oauthlib.flow import Flow

    secret_path = config.GOOGLE_CLIENT_SECRET_PATH
    token_path = config.GOOGLE_TOKEN_PATH
    if not os.path.exists(secret_path):
        raise SystemExit(
            f"Missing {secret_path}.\n"
            "Create it in Google Cloud Console: new project → enable Calendar API → OAuth\n"
            "consent screen (External, Testing, add ONLY your throwaway account as a Test\n"
            "User) → Credentials → OAuth client ID → type 'Desktop app' → download JSON here.")

    flow = Flow.from_client_secrets_file(secret_path, SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline",
                                         include_granted_scopes="true")

    print("\n" + "=" * 78)
    print("STEP 1 — open this URL in your browser (sign in as the THROWAWAY account):\n")
    print(auth_url)
    print("\nSTEP 2 — you'll see the consent screen. If an 'unverified app' warning appears,")
    print("         click Advanced → 'go to wf2-demo (unsafe)'. Then click Allow / Continue.")
    print("\nSTEP 3 — your browser will then try to open a 'localhost' page and show")
    print("         'This site can't be reached / ERR_CONNECTION_REFUSED'. THAT IS EXPECTED.")
    print("         Copy the FULL URL from the browser's address bar — it looks like")
    print("         http://localhost/?state=...&code=4/0A...&scope=...")
    print("=" * 78 + "\n")

    response_url = input("Paste that full URL here and press Enter:\n> ").strip()
    if not response_url:
        raise SystemExit("No URL pasted — nothing to do.")

    flow.fetch_token(authorization_response=response_url)
    creds = flow.credentials

    os.makedirs(os.path.dirname(token_path) or ".", exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print(f"\n✅ Token cached to {token_path}.")
    if not creds.refresh_token:
        print("⚠️  No refresh token returned — revoke the app's access in your Google account")
        print("    (myaccount.google.com → Security → Third-party access) and re-run this,")
        print("    so the consent prompt issues a fresh refresh token.")
    print("\nNext: make sure secrets/google_calendars.json maps bob/chen to your demo")
    print("calendars, then set CALENDAR_BACKEND=google in .env and restart the backend.")


if __name__ == "__main__":  # pragma: no cover
    main()
