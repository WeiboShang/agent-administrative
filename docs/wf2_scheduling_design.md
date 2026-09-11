# WF2 — Explainable, Context-Aware Meeting Lifecycle Assistant

> **Status:** implemented design record; final code verification completed 2026-08-23
> **Last updated:** 2026-08-23
> **Authority:** code is authoritative for behaviour. The authoritative formal WF2 result
> is V3.5 under the `Part A Final` evidence boundary; see [`results.md`](results.md) §1.
> **Scope decision:** cross-time-zone optimisation is out of scope for this version.

---

## 1. Positioning

WF2 is not only a natural-language calendar form. It is an explainable,
context-aware meeting lifecycle assistant supporting:

```text
create → recommend times → modify → reschedule → cancel
       → reuse meeting history → optimise recurring meetings
```

The central design is hybrid:

```text
Natural-language request or reusable meeting context
                         ↓
LLM semantic interpretation
                         ↓
Structured operation and constraint specification
                         ↓
Deterministic validation, candidate search and ranking
                         ↓
Explainable Top-K options in the frontend
                         ↓
Human selection and approval
                         ↓
Calendar execution and audit record
```

The LLM is a **semantic compiler**. It does not invent availability, decide
whether a slot is free, or execute a calendar mutation. Deterministic code
resolves dates and identities, checks state, enforces constraints, ranks
candidates and executes only the human-approved action.

This is the principal distinction from a chatbot that only converts natural
language into conventional form fields.

## 2. Goals

1. Let a user specify a date window and preferences without first selecting an
   exact time.
2. Return feasible, meaningfully different scheduling choices rather than one
   opaque answer.
3. Explain satisfied constraints, violated preferences and recommendation
   trade-offs.
4. Support the full meeting lifecycle: create, update, reschedule, cancel and
   reuse.
5. Reuse confirmed context from recurring meetings, projects and previous
   meetings.
6. Minimise disruption when an existing meeting must move.
7. Preserve the mandatory human-approval gate before any external action.
8. Log deterministic evidence for later baselines and ablations.

## 3. Non-goals

The current version will not implement:

- cross-time-zone optimisation or cross-region fairness;
- autonomous multi-agent negotiation;
- automatic email negotiation with participants;
- movement of events the user did not explicitly select;
- approval-free create, update, reschedule or cancel actions;
- a learned ranking model or reinforcement learning;
- audio transcription or meeting-minute generation;
- LangGraph solely for orchestration novelty.

Timestamps should still be stored in UTC and user timezone metadata retained so
cross-time-zone support can be added later. For now, the UI displays the
organiser's configured local time.

## 4. Current baseline and required change

The implemented WF2 provides natural-language extraction,
deterministic relative-date resolution, participant lookup, a stateful seeded
calendar, participant/room conflict checks, human editing and approval,
alternative slots after conflict, persistent records, in-app notifications, `.ics` export,
and Google Calendar API synchronisation in the current interactive configuration.

The principal limitation is that the user usually proposes a specific time
first. Alternatives are mainly generated after that time conflicts. The new
workflow must also support open-window requests such as:

- “Find a 30-minute afternoon slot for Bob and Alice next week.”
- “Arrange the earliest project review before Friday.”
- “Prefer Meeting Room A and leave a 15-minute buffer.”
- “Move Tuesday's budget meeting to another time this week.”
- “Schedule the next Project Alpha sync using the previous settings.”

Missing an exact time should trigger calendar search, not force the user to
complete another form.

## 5. Supported operations

| Operation | Meaning |
|---|---|
| `CREATE` | Create a new meeting |
| `UPDATE` | Change participants, duration, room, mode, agenda or other fields |
| `RESCHEDULE` | Find a new time for an existing meeting while preserving its context |
| `CANCEL` | Cancel one meeting or a selected recurrence scope |
| `REUSE` | Create a meeting from a previous event or reusable context |

`RESCHEDULE` is separated from general `UPDATE` because it requires candidate
search and minimal-disruption ranking. Recurring meetings extend these
operations; they are not a separate operation type.

### 5.1 Target-event resolution

For `UPDATE`, `RESCHEDULE` and `CANCEL`, the target is resolved using:

- event ID when the action starts from an event card;
- title or project;
- approximate date/time;
- participants;
- recurrence series.

If multiple events match, deterministic choices are shown. The LLM must not
silently select one.

## 6. Entry points

### 6.1 Quick Create

A compact conventional form remains available with title, participants, date,
start time, duration, room/mode and description. Quick Create is a reliable
fallback and the traditional-interface baseline for later evaluation. It is not
the research innovation.

### 6.2 Smart Schedule

The user supplies a natural-language request with an exact time or search
window. Optional structured controls can pin important constraints.

Example:

> Find a 30-minute afternoon slot for Bob and Chen next week. Avoid lunch,
> prefer Meeting Room A, and leave a 15-minute buffer.

### 6.3 Existing-event actions

Every event details view exposes:

- **Edit**
- **Reschedule**
- **Cancel**
- **Schedule again**

Recurring/project context views may also expose **Schedule next occurrence**.

## 7. Interaction flow

One scheduling interaction follows:

```text
1. Start a request or select reusable context
2. Identify operation and target event, if applicable
3. Extract structured fields and constraints
4. Resolve participants, rooms and dates
5. Ask one targeted clarification only when necessary
6. Generate feasible candidates
7. Rank and diversify candidates
8. Display explainable Top-K options
9. User selects, edits constraints or requests more options
10. Revalidate the selected/edited option
11. Display final summary or before/after diff
12. Execute only after explicit approval
13. Save result and audit evidence
```

An absent exact time is not itself a clarification condition. Clarification is
reserved for information the calendar cannot safely infer, for example:

- a participant name matches multiple directory records;
- no participant can be resolved;
- a relative date has two plausible interpretations;
- an update request matches multiple meetings;
- a recurring cancellation does not specify scope.

Clarification options come from deterministic records. The LLM may phrase the
question but cannot invent available options.

## 8. Structured scheduling specification

The LLM output is validated against a schema similar to:

```json
{
  "operation": "CREATE",
  "target_event_id": null,
  "title": "Project Alpha weekly sync",
  "participants": ["Bob", "Alice", "Chen"],
  "duration_minutes": 30,
  "date_window": {
    "start": "2026-08-03",
    "end": "2026-08-07"
  },
  "exact_start": null,
  "location": {
    "mode": "in_person",
    "preferred_room": "Meeting Room A",
    "online_fallback": true
  },
  "hard_constraints": {
    "all_required_participants_available": true,
    "working_hours_only": true
  },
  "soft_preferences": {
    "preferred_period": "afternoon",
    "avoid_lunch": true,
    "buffer_before_minutes": 15,
    "buffer_after_minutes": 15
  },
  "context_id": "project-alpha-weekly",
  "recurrence": null,
  "evidence": []
}
```

Every value records provenance:

- explicit current request;
- manual review edit;
- reusable meeting context;
- confirmed user preference;
- system default.

Precedence is:

```text
explicit current request / manual edit
    > current reusable meeting context
    > confirmed user preference
    > system default
```

Historical preference must never overwrite an explicit current request.

## 9. Constraint model

### 9.1 Hard constraints

Hard constraints must pass before a candidate is recommended:

- organiser availability;
- required-participant availability;
- sufficient continuous duration;
- selected date window;
- mandatory working-hour restriction;
- mandatory room availability;
- required room capacity/equipment;
- valid recurrence boundary.

A hard conflict is a blocker, not a warning that can be silently overridden.

### 9.2 Soft preferences

Soft preferences influence ranking:

- morning/afternoon preference;
- avoid lunch;
- meeting buffers;
- preferred room;
- in-person/online preference;
- earliest suitable time;
- reusable-context pattern;
- confirmed user preference;
- minimal disruption from the original meeting.

The UI distinguishes:

- **blocker** — cannot proceed;
- **preference warning** — may proceed after explicit review;
- **informational note** — no approval consequence.

### 9.3 Rooms

Where fixture data permits, room constraints include availability, capacity,
location, equipment, meeting mode and online fallback. The first implementation
may use a small deterministic synthetic room directory.

### 9.4 Buffers

Before/after buffers apply to participant back-to-back meetings and optional
room turnover. A buffer is soft by default but can be explicitly marked
mandatory.

## 10. Explainable multi-constraint Top-K scheduling

### 10.1 Definition

Top-K returns the highest-quality `K` feasible candidates instead of requiring
the user to guess a time or accept one opaque answer. Default `K = 3`.

```text
candidate generation
       ↓
hard-constraint filtering
       ↓
soft-preference scoring
       ↓
candidate diversification
       ↓
Top-K result with reason codes
```

The LLM never generates calendar availability or candidate scores.

### 10.2 Candidate generation

Candidates are enumerated over the requested date window at a configurable
interval, initially 30 minutes.

Initial limits:

- default window: next five working days;
- maximum interactive window: 30 days;
- default boundary: configured working hours;
- an exact-time request is also validated as a candidate.

If no feasible candidate exists, explain the binding constraints and offe
controlled relaxations such as widening the date range, using another room,
removing a soft buffer or using online fallback. Never silently relax a hard
constraint.

### 10.3 Scoring dimensions

| Dimension | Purpose |
|---|---|
| Request preference | Match explicit preferences in the current request |
| Context match | Match the project or recurring-meeting pattern |
| User preference | Match confirmed general preferences |
| Buffer quality | Preserve preparation/transition time |
| Room quality | Match preferred room, capacity, equipment and mode |
| Urgency | Prefer earlier slots for deadline/earliest requests |
| Disruption | Penalise changes from an existing event |
| Series consistency | Remain near an established recurring pattern |

Conceptually:

```text
candidate score =
    request preference score
  + context match score
  + confirmed user preference score
  + buffer score
  + room score
  + urgency score
  - disruption cost
```

Weights are configurable and stored outside prompts. Component scores are
retained for audit and later evaluation. Initial weights are engineering
parameters, not claims of learned optimality; they can later be calibrated on a
development set without training an LLM.

### 10.4 Operation-specific ranking

For a new meeting, rank by:

1. all hard constraints;
2. explicit request preferences;
3. reusable meeting context;
4. confirmed user preferences;
5. buffers;
6. room preference;
7. earliest time after the preceding criteria.

For rescheduling, rank by:

1. all hard constraints;
2. preservation of participants and duration;
3. proximity to the original date/time;
4. preservation of room and meeting mode;
5. recurring-series consistency;
6. buffers and remaining preferences.

### 10.5 Minimal-disruption cost

```text
disruption cost =
    date-change cost
  + time-distance cost
  + room-change cost
  + meeting-mode-change cost
  + series-pattern deviation
  + newly introduced preference violations
```

Only the explicitly selected event may move. WF2 does not rearrange unrelated
calendar events to improve the score.

### 10.6 Candidate diversity

Top-K must not return three near-identical adjacent slots. Default options:

1. **Recommended** — best overall match;
2. **Earliest available** — earliest feasible option;
3. **Best context match** for create/reuse, or **Lowest disruption** fo
   rescheduling.

If labels resolve to the same slot, use the next distinct candidate. A minimum
separation is configurable.

### 10.7 Explainability contract

Every recommendation includes deterministic reasons and warnings:

```json
{
  "candidate_id": "slot-20260804-1430-room-a",
  "start": "2026-08-04T13:30:00Z",
  "end": "2026-08-04T14:00:00Z",
  "label": "recommended",
  "room_id": "room-a",
  "score_components": {
    "request_preference": 30,
    "context_match": 20,
    "user_preference": 10,
    "buffer": 15,
    "room": 15,
    "urgency": 5,
    "disruption": 0
  },
  "reason_codes": [
    "all_participants_available",
    "preferred_afternoon",
    "preferred_room_available",
    "buffer_satisfied",
    "matches_meeting_context"
  ],
  "warning_codes": []
}
```

The frontend maps codes to concise text. The LLM may improve wording but cannot
introduce reasons absent from the calculation. Numeric scores remain available
for debugging/evaluation; the main UI shows reasons and trade-offs rather than
false precision.

## 11. Frontend design

### 11.1 Recommendation cards

Top-K results appear as selectable cards, not only as chat text:

```text
┌ Recommended ─────────────────────────────────┐
│ Tuesday, 4 August · 14:30–15:00              │
│ Meeting Room A                               │
│                                               │
│ ✓ All required participants are available    │
│ ✓ Matches the requested afternoon period     │
│ ✓ Keeps a 15-minute buffer                    │
│ ✓ Matches the Project Alpha meeting pattern  │
│                                               │
│ [Select] [View details]                       │
└───────────────────────────────────────────────┘
```

Cards display date/time, duration, room/mode, recommendation label, satisfied
constraints, warnings and — for rescheduling — differences from the original
event.

Actions:

- **Select**
- **View details**
- **Change constraints**
- **Find more times**
- **Enter a time manually**

Selection opens final review; it never executes immediately.

### 11.2 Modification diff

Updates and reschedules show a before/after diff:

```diff
Participants
- Bob, Alice
+ Bob, Alice, Chen

Duration
- 30 minutes
+ 60 minutes

Time
- Tuesday 14:00
+ Tuesday 15:00
```

Any feasibility-affecting edit triggers revalidation before approval is enabled.

### 11.3 Cancellation review

Before cancellation, show the exact event, date/time, participants, number of
people affected, optional reason and recurrence scope.

## 12. Two-part context model

The previous three-layer proposal is reduced. Series and project/topic
templates share the same defaults and are represented by one reusable context.
Raw history is evidence, not another memory layer.

### 12.1 Reusable Meeting Context

```json
{
  "context_id": "project-alpha-weekly",
  "context_type": "series",
  "name": "Project Alpha Weekly Sync",
  "project_id": "project-alpha",
  "default_title": "Project Alpha Weekly Sync",
  "default_participants": ["bob-id", "alice-id", "chen-id"],
  "default_duration_minutes": 30,
  "default_mode": "online",
  "preferred_room_id": null,
  "preferred_period": "Tuesday afternoon",
  "buffer_before_minutes": 15,
  "buffer_after_minutes": 15,
  "agenda_template": [
    "Review previous actions",
    "Discuss blockers",
    "Agree next actions"
  ],
  "recurrence_rule": "weekly",
  "source_event_ids": []
}
```

Context types:

- `series` — recurring meeting with a recurrence rule;
- `project` — project/topic template without mandatory recurrence;
- `saved` — user-saved reusable template.

**Schedule again** may use one previous event as temporary context without first
creating a permanent template.

### 12.2 Confirmed Preference Profile

```json
{
  "avoid_before": "10:00",
  "preferred_buffer_minutes": 15,
  "preferred_meeting_mode": "online",
  "category_preferences": {
    "project_review": {
      "preferred_period": "Tuesday afternoon"
    }
  }
}
```

Preferences come from direct configuration or a suggestion explicitly confirmed
by the user. For example:

> Four of the last five Project Alpha meetings were moved to Tuesday
> afternoon. Save “Tuesday afternoon” as the preferred period for this context?

History alone must not silently become an active preference.

### 12.3 History as evidence

Meeting history supports Schedule Again, repeated-pattern detection, preference
suggestions and later analysis. It is not a third configuration layer. This
avoids storing the same preference independently in history, a project template
and a user profile.

## 13. Historical reuse

**Schedule again** copies title/template, project link, participants, duration,
room/mode, buffers and agenda. It does not blindly copy the old date/time. The
user selects a search window:

- next five working days;
- next week;
- custom range.

The system then runs Top-K scheduling with the reused context.

Pattern matching initially prioritises series ID, project ID and saved context
ID. Semantic title/agenda similarity may suggest a context but requires use
confirmation; title equality alone is insufficient because unrelated projects
may both use “Weekly Sync”.

## 14. Recurring meeting optimisation

### 14.1 Fixed recurrence

Initial recurrence supports weekly, fortnightly and monthly rules. Update,
reschedule and cancellation require one scope:

- this occurrence;
- this and following occurrences;
- entire series.

### 14.2 Smart Next Occurrence

**Schedule next occurrence** reuses participants, duration, mode/room, agenda,
buffers and established period preference, then searches the next window and
displays fresh Top-K choices. This handles calendar changes better than blindly
copying the previous time.

### 14.3 Later extension

A later phase may prepare Top-K candidates a configured number of days before
the next occurrence, but creation or movement still requires approval. Fully
autonomous recurring rescheduling is out of scope.

## 15. Update, reschedule and cancellation semantics

### 15.1 Update

Updates may change title, description, participants, duration, room/mode,
agenda or recurrence. Participant, duration, room, mode, recurrence and time
changes require a fresh feasibility check.

### 15.2 Reschedule

Rescheduling preserves context and searches for a new time. Top-K explains the
time/date difference, room/mode changes, buffers, series deviation and
soft-preference trade-offs.

### 15.3 Cancel

Cancellation requires resolved event identity, recurrence scope where relevant,
final confirmation and an audit record. Notifications are produced only afte
successful execution.

## 16. Backend contracts

Exact routes may follow the current router structure, but responsibilities
should be separated:

```text
POST /schedule/parse
    Interpret operation, fields and constraints.

POST /schedule/candidates
    Resolve records, validate hard constraints, score and return Top-K.

POST /schedule/revalidate
    Recheck a selected or manually edited candidate.

POST /schedule/execute
    Execute an approved create/update/reschedule/cancel operation.

GET /schedule/events/{event_id}
    Return event details and reusable context.

POST /schedule/events/{event_id}/reuse
    Build a draft from an existing event.

GET/POST/PATCH /schedule/contexts
    Manage reusable meeting contexts.

GET/PATCH /schedule/preferences
    Read and update confirmed preferences.
```

Candidate responses include IDs, UTC start/end, display timezone, room/mode,
score components, reason/warning codes, provenance and a calendar validation
token. Execution rejects stale validation tokens and requires an idempotency key.

## 17. Correctness requirements before expansion

1. Include the organiser in availability and conflict checks.
2. After participant edits, use newly resolved IDs/details for validation,
   notifications and the optional external demo.
3. Revalidate every feasibility-affecting edit and show fresh blockers/warnings
   before approval.
4. Make conflict validation and booking atomic, or use calendar-version
   optimistic concurrency.
5. Require an idempotency key for every mutation.
6. Distinguish blockers, soft-preference violations and information.
7. Generate alternatives for open-window requests, not only explicit conflicts.
8. Preserve evidence/provenance for extracted and inherited values.
9. Create notifications only after the calendar mutation succeeds.
10. Record requested and executed recurrence scope.

## 18. Execution backends and safety boundary

The evaluated core remains synthetic, self-contained and reproducible:

- fictional people and meetings only;
- stateful local `RecordStore` calendar;
- mock in-app notification records;
- `.ics` export;
- evaluation never calls an external booking path.

The interactive Google Calendar backend remains isolated from formal evaluation under the
constraints in `CLAUDE.md`: dedicated project account, no real
attendees, no attendee email, minimal `calendar.events` scope, credentials under
gitignored `secrets/`, and never part of evaluation. The current local environment selects
`google`; the repository fallback is `mock`. Create/update/reschedule/cancel use the same
interface and preserve the local approved record if Google is unavailable.

## 19. Implementation phases

### Phase 0 — correctness

- fix organiser conflict checking;
- fix stale participant data after edits;
- add revalidation preview;
- add atomic/versioned booking protection;
- add idempotency;
- formalise blocker/warning/note severity;
- preserve request/edit provenance.

### Phase 1 — distinction MVP

- add Quick Create as the conventional baseline;
- support Smart Schedule with open date windows;
- implement hard/soft constraints;
- implement deterministic candidate generation;
- implement configurable scoring and score breakdown;
- implement diversified Top-3 recommendations;
- add reason codes and frontend cards;
- support `CREATE`, `UPDATE`, `RESCHEDULE`, `CANCEL` and `REUSE`;
- show update/reschedule diffs;
- preserve final human approval.

### Phase 2 — context and recurrence

- add Reusable Meeting Context;
- add Schedule Again;
- add Confirmed Preference Profile;
- add confirmed preference suggestions;
- support fixed recurrence and recurrence scopes;
- add Smart Next Occurrence;
- refine minimal-disruption ranking.

### Phase 3 — optional extensions

- prepare recurring candidates in advance while retaining approval;
- suggest project/topic context associations;
- calibrate ranking parameters on a development set;
- consider cross-time-zone optimisation separately.

## 20. Focused operational Analysis

> **Status: planned.** This page supports day-to-day calendar coordination. It describes
> actual workload, capacity and change history; it does not judge the scheduling model.
> Top-K ranking quality, selected-rank analysis, baseline comparisons and ablations remain
> deferred to Evaluation.

### Questions the page must answe

1. When is the calendar busiest and where is capacity constrained?
2. Which participants or rooms carry the highest meeting load?
3. How much calendar change is being created through create, reschedule and cancel actions?
4. Which entry paths and reusable contexts are being used in normal operation?

### Primary tiles and views

| View | Required content | Presentation rule |
|---|---|---|
| workload tiles | upcoming meetings · committed hours · rescheduled events · cancelled events | use a selected time window; never imply causality or “time saved” |
| booking-density heatmap | meetings by calendar date | retain the existing navigable date grid and explicit empty state |
| participant load | meeting count and committed duration by participant | allow date/project filtering; count and duration are separate measures |
| room utilisation | booking count and occupied duration by room | label unassigned/online meetings separately |
| lifecycle trend | created · rescheduled · cancelled by week/month | derive from the versioned event/change log, not current-event totals alone |
| scheduling entry mix | Quick Create · Smart Schedule · Schedule Again · Recurring | operational adoption only; do not interpret it as model quality |
| reusable context summary | most-used confirmed project/series/saved contexts | link to the underlying context and its future occurrences |

The current Meetings booked / Days with meetings / Busiest day / Time committed tiles,
booking-density heatmap, room utilisation and participant-load bars are the baseline.
Retain useful components, then add lifecycle and context views after update/cancel/reuse
provenance exists. Do not fabricate these from incomplete current records.

### Data and presentation rules

- All counts use an explicit date window and the user's calendar locale.
- Rescheduling counts one change operation, not both a cancellation and a new meeting.
- Recurrence views distinguish one occurrence from an entire series.
- Participant/room load is descriptive capacity information, not a fairness judgement.
- “Conflicts avoided” and “time saved” are prohibited unless a defined counterfactual and
  reliable timing data exist.
- Recommendation rank, score components, constraint-validity rate, edit burden and
  with/without-memory comparisons belong only in Evaluation.
- Every chart must support a record-level drill-down or filter that helps the coordinato
  act on the result.

Initial filters are time range, participant, room, project/context and operation type.

## 21. Evaluation hooks and final evidence

The logging hooks below are implemented. The final authoritative WF2 result is V3.5:
70 matched E2E cases / 140 condition executions plus a separate 20-case mechanism suite.
This is the WF2 component of `Part A Final`; it does not test the Google provider API or
the full update/cancel/reuse lifecycle.

WF2 logs:

- interface mode: Quick Create, NL extraction or Smart Schedule;
- operation type and structured constraints;
- candidate counts before/after hard filtering;
- Top-K score components;
- selected candidate and rank;
- reasons/warnings shown;
- clarification turns and manual edits;
- revalidation result and task outcome;
- execution latency;
- reused context/preference sources;
- rescheduling disruption components.

This enables later comparisons:

```text
manual form
vs. natural-language field extraction
vs. constraint-aware Top-K assistant
```

and ablations with/without reusable context and confirmed preferences. The goal
is not an opaque maximum score; it is reduced user effort with valid,
explainable and human-approved calendar operations.

## 22. Acceptance criteria

WF2 is complete when:

1. A user can request a meeting without an exact time.
2. Up to three feasible, meaningfully different choices are returned.
3. Every choice has deterministic reasons and warnings.
4. Organiser, participants, duration, room and mandatory constraints are checked.
5. The user can select a result or change the constraints.
6. Feasibility-affecting edits are revalidated before approval.
7. Create, update, reschedule, cancel and reuse are supported.
8. Rescheduling explains minimal disruption.
9. A previous meeting can be reused without blindly copying its old time.
10. Recurring meetings support occurrence scope and Smart Next Occurrence.
11. Context/preferences never overwrite an explicit current request.
12. No mutation occurs without explicit human approval.
13. Execution is idempotent and protected from stale conflict checks.
14. Cross-time-zone optimisation is not required for this release.

## 23. Research grounding

- Google DeepMind, **NATURAL PLAN** — meeting planning and calendar scheduling:
  <https://arxiv.org/abs/2406.04520>
- NATURAL PLAN repository and deterministic evaluators:
  <https://github.com/google-deepmind/natural-plan>
- Microsoft, **Task-Oriented Dialogue as Dataflow Synthesis / SMCalFlow**:
  <https://microsoft.github.io/task_oriented_dialogue_as_dataflow_synthesis/>
- Google Research, **Schema-Guided Dialogue Dataset**:
  <https://github.com/google-research-datasets/dstc8-schema-guided-dialogue>
- **Foundations of Collaborative Task-Oriented Dialogue: What's in a Slot?**:
  <https://aclanthology.org/W19-5924/>
- **Ask-before-Plan** — targeted clarification before planning:
  <https://arxiv.org/abs/2406.12639>
- **Decision-Oriented Dialogue** — mixed-initiative choice over large option spaces:
  <https://aclanthology.org/2024.tacl-1.50/>
- **PEARL / CalConflictBench** — preference-grounded conflict resolution:
  <https://arxiv.org/abs/2601.11957>
- **CalBench** — disruption/fairness context for future work, not current scope:
  <https://arxiv.org/abs/2605.09823>
