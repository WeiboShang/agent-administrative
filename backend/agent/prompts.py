SYSTEM_PROMPT = (
    "You are an enterprise administrative assistant. "
    "Analyze incoming communication and generate structured drafts for human review. "
    "Always respond with valid JSON only — no markdown, no explanation. "
    "Use fictional names (Alice, Bob, Chen) and synthetic data only."
)

SCHEDULING_PROMPT = """\
Extract meeting-scheduling information from this communication. Do NOT compute or resolve
the date — copy it exactly as the sender expressed it (e.g. "next Tuesday"). The system
resolves relative dates and looks up participants; your job is only to read the message.

Communication:
{input}

Respond with a JSON object containing exactly these fields:
- title: (string) short meeting title
- participants: (array of strings) names of people to invite, as written
- date: (string) the date AS STATED ("next Tuesday", "2026-07-07", ...), or null if none
- time: (string) start time in HH:MM 24h, or null if not stated
- duration_minutes: (integer) if explicitly stated, else null
- location: (string) room name or "Online", or null if not mentioned
- mode: (string) "in_person" or "virtual", or null
- agenda: (string) one-line agenda, or "" if none

JSON only."""

TRIAGE_PROMPT = """\
You are triaging an incoming enterprise message/thread. Read it and detect any
administrative ACTIONS it implies.

Channel: {source} — an email is usually a single formal request; a chat thread is
multi-party and the actionable line is often buried in small talk.

Thread:
{input}

Respond with JSON only:
{{
  "summary": "one-sentence summary naming WHO wants WHAT, WHEN (keep concrete day/time/names)",
  "key_points": ["the 3-5 points that matter most — actionable items first (with their day, time and people); ignore small talk and trivia"],
  "detected_actions": [
    {{
      "action_type": "schedule_meeting | expense_claim | none",
      "operation": "create | amend | cancel",
      "target_action_id": "existing action ID for amend/cancel, otherwise null",
      "model_confidence": 0.0,
      "source_evidence": [{{"message_id": "message ID from the input", "span": "exact words"}}],
      "field_sources": {{"field_name": {{"message_id": "...", "span": "exact words"}}}},
      "attachment_ids": ["only attachment IDs explicitly present in the input"],
      "rationale": "why",
      "model_seed_fields": {{}}
    }}
  ],
  "memo_items": [
    {{
      "text": "an explicit follow-up, commitment, important date or unresolved question",
      "item_type": "todo | important_date",
      "date_phrase": "date as stated or null",
      "resolved_date": null,
      "date_relation": "on | before | after | null",
      "model_confidence": 0.0,
      "source_evidence": [{{"message_id": "message ID from the input", "span": "exact words"}}]
    }}
  ]
}}

Rules:
- Use "create" for a new request. Use "amend" or "cancel" only when a later message clearly
  changes/calls off an existing action; copy its exact action_id into target_action_id.
- "schedule_meeting" when the thread asks to meet / sync / call. model_seed_fields:
  {{"title": "...", "participants": ["names"], "date": "AS STATED e.g. next Tuesday",
    "time": "HH:MM or null", "duration_minutes": integer or null,
    "location": "or null", "agenda": "or null"}}
- "expense_claim" only for a request to reimburse/submit a NEW expense. model_seed_fields:
  {{"employee_name": "...", "vendor": "or null", "date": "or null", "amount": number or null,
    "currency": "ISO code or null", "category": "or null", "business_purpose": "or null",
    "cost_centre": "or null"}}
- Leave, onboarding, procurement, IT and other unsupported workflows may create memo_items
  for explicit dates/follow-ups, but never workflow actions.
- Create a memo only for an explicit commitment, confirmed event, important date/deadline,
  required follow-up or unresolved question requiring action. Do not duplicate a supported
  meeting/expense action as a memo. Do not infer a standard checklist.
- Every evidence message_id must be copied from the bracketed input IDs and every span must
  be verbatim text from that message. Never invent attachment IDs.
- If nothing actionable (FYI, thanks, chit-chat), return one action with action_type "none".
- Copy dates AS STATED; do not compute them. CODE resolves unambiguous dates.

JSON only."""

DECISION_NOTE_PROMPT = """\
You are drafting an internal notification email about an expense-claim decision.

Facts (the ONLY information you may use):
{input}

Write a short professional note to the employee. Respond with JSON only:
{{"subject": "...", "body": "..."}}

Rules:
- Use ONLY the facts above. Do not invent amounts, dates, names, policies or reasons.
- State the decision and the claim's key facts (vendor, amount, date).
- If the decision is "rejected", state the given decision_reason plainly.
- If policy_flag lines are present, mention what was flagged in one sentence.
- No placeholders like [Name] or [Company]; sign off as "Finance Admin Desk".
- Body: 3-6 sentences, plain text.

JSON only."""

PROMPT_MAP: dict[str, str] = {
    "scheduling": SCHEDULING_PROMPT,
    "triage": TRIAGE_PROMPT,
    "decision_note": DECISION_NOTE_PROMPT,
}


# ── Feedback-conditioned prompting (WF1) ──────────────────────────────────────────────
# The reviewer's Dismiss decisions are already recorded but were never fed back. Appending a
# few of them as negative examples is a PROMPT-LAYER loop, not persistent agent memory: no
# state is carried inside the model, and the agent still only proposes. Appended only when
# examples are supplied, so the baseline prompt stays byte-identical and the A/B is fair.
FEEDBACK_BLOCK = """

The reviewer has previously DISMISSED wordings like these as NOT actionable:
{examples}
Judge the thread above by the same standard."""


def feedback_block(examples: list[str]) -> str:
    return FEEDBACK_BLOCK.format(examples="\n".join(f'- "{e}"' for e in examples))
