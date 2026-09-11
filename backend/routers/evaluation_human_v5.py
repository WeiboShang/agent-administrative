"""V5 human-evaluation API with a gold-free reviewer projection."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..evals.human_v5 import (
    HumanCaseSubmissionV5,
    asset_path_v5,
    human_session_store_v5,
    preflight_case_v5,
    protocol_payload_v5,
)


router = APIRouter(prefix="/api/eval/v5/human")


class CreateSessionRequestV5(BaseModel):
    reviewer_id: str = Field(default="evaluation-reviewer", min_length=1, max_length=64)
    ethics_confirmed: bool = False


class PolicyPreflightRequestV5(BaseModel):
    final_fields: dict = Field(default_factory=dict)


def _not_found(error: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=f"not found: {error.args[0]}")


@router.get("/protocol")
async def human_protocol_v5() -> dict:
    return protocol_payload_v5()


@router.post("/sessions")
async def create_session_v5(req: CreateSessionRequestV5) -> dict:
    reviewer_id = req.reviewer_id.strip()
    if not reviewer_id:
        raise HTTPException(status_code=422, detail="reviewer_id cannot be blank")
    try:
        return human_session_store_v5.create(
            reviewer_id=reviewer_id, ethics_confirmed=req.ethics_confirmed
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/sessions/{session_id}")
async def get_session_v5(session_id: str) -> dict:
    try:
        return human_session_store_v5.view(human_session_store_v5.get(session_id))
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/sessions/{session_id}/confirm-ethics")
async def confirm_ethics_v5(session_id: str) -> dict:
    try:
        return human_session_store_v5.confirm_ethics(session_id)
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/sessions/{session_id}/cases/{case_id}/start")
async def start_case_v5(session_id: str, case_id: str) -> dict:
    try:
        material = human_session_store_v5.start_case(session_id, case_id)
        return material.model_dump(mode="json")
    except KeyError as error:
        raise _not_found(error) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/sessions/{session_id}/cases/{case_id}/complete")
async def complete_case_v5(
    session_id: str, case_id: str, submission: HumanCaseSubmissionV5
) -> dict:
    try:
        return human_session_store_v5.complete_case(session_id, case_id, submission)
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/sessions/{session_id}/cases/{case_id}/preflight")
async def preflight_case_policy_v5(
    session_id: str, case_id: str, req: PolicyPreflightRequestV5,
) -> dict:
    try:
        session = human_session_store_v5.get(session_id)
        human_session_store_v5._assert_current_protocol(session)
        row = session.get("cases", {}).get(case_id)
        if not row or row.get("state") != "started":
            raise ValueError("case must be the active started case")
        return preflight_case_v5(case_id, req.final_fields)
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/sessions/{session_id}/finalize")
async def finalize_session_v5(session_id: str) -> dict:
    try:
        return human_session_store_v5.finalize(session_id)
    except KeyError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/history")
async def human_history_v5() -> dict:
    return {"items": human_session_store_v5.history()}


@router.get("/assets/{case_id}")
async def human_asset_v5(case_id: str) -> FileResponse:
    try:
        return FileResponse(asset_path_v5(case_id))
    except (KeyError, FileNotFoundError) as error:
        raise HTTPException(status_code=404, detail="case asset not found") from error
