import os
from dotenv import load_dotenv

load_dotenv()

# Live model calls require this key, but importing the application, running unit tests,
# and replaying the frozen evaluation evidence do not.  Keep configuration importable in
# a freshly cloned, offline environment; the model adapters raise a focused error only
# when a live call is requested.
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")

# Text model (WF1 triage, WF2 scheduling extraction).
LLM_MODEL: str = "openai/gpt-oss-120b"

# Vision model (WF3 multimodal receipt extraction). Qwen3.6-27B — the only remaining
# vision-capable model on this Groq account after llama-4-scout's retirement
# (2026-07-17; scout's final numbers + raw outputs are frozen in data/eval_cache/ and
# docs/results.md §2.7). Emits a <think> block before JSON — the parser strips it.
VISION_MODEL: str = "qwen/qwen3.6-27b"

# Where the live workspace (threads / events / submissions) is kept. A FILE means the work
# you did — booked meetings, submitted claims, triaged threads — survives a restart, which
# is what an actual workspace has to do. Set to ":memory:" for the old reset-on-restart
# behaviour (handy for a pristine demo or screenshots).
#
# This does NOT weaken evaluation reproducibility (CLAUDE.md §3.4): every eval path builds
# its own fresh `RecordStore(":memory:")` and seeds it — none of them touch this store, and
# nothing in the codebase calls `reset()` on it. The fixtures are seeded into the file only
# when it is empty, so a restart never stacks a second copy on top of your data.
RECORD_STORE_PATH: str = os.environ.get("RECORD_STORE_PATH", "data/workspace.db")

# WF2 interactive calendar backend (docs/wf2_scheduling_design.md §18): "google" is used by
# the current local deployment; "mock" remains the safe repository fallback when the setting
# is absent. The evaluation harness never reads this switch and injects its mock explicitly.
# This flag affects only human-approved interactive scheduling routes.
CALENDAR_BACKEND: str = os.environ.get("CALENDAR_BACKEND", "mock")
# Credentials for the "google" backend — a dedicated project account only (never a real
# personal account), gitignored under secrets/. See backend/scripts/google_auth_setup.py.
GOOGLE_TOKEN_PATH: str = os.environ.get("GOOGLE_TOKEN_PATH", "secrets/google_token.json")
GOOGLE_CLIENT_SECRET_PATH: str = os.environ.get(
    "GOOGLE_CLIENT_SECRET_PATH", "secrets/client_secret.json")
GOOGLE_CALENDARS_PATH: str = os.environ.get(
    "GOOGLE_CALENDARS_PATH", "secrets/google_calendars.json")
