"""Stable WF1 action identity/version contract.

Old action shapes are accepted at this one migration boundary, but the returned production
record contains only the canonical field names used by the current UI and workflow.
"""

OPERATIONS = {"create", "amend", "cancel"}


def ensure_action_contract(actions: list[dict], *, thread_id: str) -> list[dict]:
    """Return copies of actions with stable identity, version and proposal snapshots."""
    contracted: list[dict] = []
    used_ids: set[str] = set()
    for index, original in enumerate(actions):
        action = dict(original)
        fallback_id = f"act-{thread_id}-{index + 1:03d}"
        action_id = action.get("action_id")
        if not isinstance(action_id, str) or not action_id.strip():
            action_id = fallback_id
        if action_id in used_ids:
            suffix = 2
            while f"{fallback_id}-{suffix}" in used_ids:
                suffix += 1
            action_id = f"{fallback_id}-{suffix}"
        used_ids.add(action_id)

        version = action.get("version", 1)
        if isinstance(version, bool):
            version = 1
        try:
            version = max(1, int(version))
        except (TypeError, ValueError):
            version = 1

        operation = action.get("operation")
        if operation not in OPERATIONS:
            operation = "create"

        legacy_seed = action.get("seed_fields")
        model_seed = action.get("model_seed_fields")
        current_seed = action.get("current_seed_fields")
        if not isinstance(model_seed, dict):
            model_seed = legacy_seed if isinstance(legacy_seed, dict) else {}
        if not isinstance(current_seed, dict):
            current_seed = legacy_seed if isinstance(legacy_seed, dict) else model_seed

        confidence = action.get("model_confidence", action.get("confidence", 0.0))
        action.update({
            "action_id": action_id,
            "version": version,
            "operation": operation,
            "target_action_id": action.get("target_action_id"),
            "model_confidence": confidence,
            "model_seed_fields": dict(model_seed),
            "current_seed_fields": dict(current_seed),
        })
        action.pop("confidence", None)
        action.pop("seed_fields", None)
        contracted.append(action)

    return contracted
