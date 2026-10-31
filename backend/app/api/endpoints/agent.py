"""Agent API endpoints (Phase 3): sessions, chat, runs, AI status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import orchestrator
from app.ai.client import GeminiClient, get_gemini_client
from app.ai.schemas.chat import (
    AgentChatRequest,
    AgentChatResponse,
    AgentMessageView,
    AgentRunDetail,
    AgentRunSummary,
    AgentSessionDetail,
    AgentSessionSummary,
    AgentStatusResponse,
    AgentToolExecutionView,
    ToolCallTrace,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models import AgentMessage, AgentRun, AgentSession, AgentToolExecution

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send an operator message to the ReliefMesh AI orchestrator",
)
def chat(
    payload: AgentChatRequest,
    db: Session = Depends(get_db),
    ai_client: GeminiClient = Depends(get_gemini_client),
):
    """Full orchestrator turn: model -> validated tool calls -> real results."""
    result = orchestrator.run_agent_turn(
        db,
        payload.message,
        payload.session_id,
        ai_client,
    )
    return AgentChatResponse(
        session_id=result.session_id,
        run_id=result.run_id,
        status="completed",
        assistant_message=result.assistant_message,
        tool_calls=[
            ToolCallTrace(
                tool_name=trace.tool_name,
                status=trace.status,
                execution_time_ms=trace.execution_time_ms,
                summary=trace.summary,
            )
            for trace in result.tool_trace
        ],
        created_at=result.created_at,
    )


@router.get(
    "/sessions",
    response_model=list[AgentSessionSummary],
    summary="List recent agent conversations",
)
def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    counts = dict(
        db.execute(
            select(AgentMessage.session_id, func.count())
            .group_by(AgentMessage.session_id)
        ).all()
    )
    sessions = db.scalars(
        select(AgentSession).order_by(AgentSession.updated_at.desc()).limit(limit)
    ).all()
    return [
        AgentSessionSummary(
            session_id=session.id,
            session_title=session.session_title,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=counts.get(session.id, 0),
        )
        for session in sessions
    ]


@router.get(
    "/sessions/{session_id}",
    response_model=AgentSessionDetail,
    summary="Full conversation history of one session",
)
def get_session(session_id: int, db: Session = Depends(get_db)):
    session = db.get(AgentSession, session_id)
    if session is None:
        raise NotFoundError(f"Agent session {session_id} not found")
    return AgentSessionDetail(
        session_id=session.id,
        session_title=session.session_title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[
            AgentMessageView(role=m.role, content=m.content, created_at=m.created_at)
            for m in session.messages
        ],
        runs=[
            AgentRunSummary(
                run_id=run.id,
                status=run.status,  # type: ignore[arg-type]
                model_name=run.model_name,
                tool_call_count=run.tool_call_count,
                error_message=run.error_message,
                created_at=run.created_at,
                completed_at=run.completed_at,
            )
            for run in session.runs
        ],
    )


@router.get(
    "/runs/{run_id}",
    response_model=AgentRunDetail,
    summary="Full run detail incl. tool executions (safe traces)",
)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(AgentRun, run_id)
    if run is None:
        raise NotFoundError(f"Agent run {run_id} not found")
    user_message = db.get(AgentMessage, run.user_message_id)
    assistant = (
        db.get(AgentMessage, run.assistant_message_id)
        if run.assistant_message_id
        else None
    )
    executions = db.scalars(
        select(AgentToolExecution)
        .where(AgentToolExecution.agent_run_id == run.id)
        .order_by(AgentToolExecution.id)
    ).all()
    return AgentRunDetail(
        run_id=run.id,
        session_id=run.session_id,
        status=run.status,
        model_name=run.model_name,
        user_message=user_message.content if user_message else "",
        assistant_message=(
            run.final_response if run.final_response is not None else (assistant.content if assistant else None)
        ),
        tool_call_count=run.tool_call_count,
        tool_executions=[
            AgentToolExecutionView(
                tool_name=execution.tool_name,
                status=execution.status,
                arguments_json=execution.arguments_json or {},
                result_json=execution.result_json or {},
                result_summary=execution.result_summary,
                execution_time_ms=execution.execution_time_ms,
                created_at=execution.created_at,
            )
            for execution in executions
        ],
        error_message=run.error_message,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get(
    "/status",
    response_model=AgentStatusResponse,
    summary="AI orchestrator configuration status (no key material)",
)
def agent_status():
    key_configured = bool(settings.gemini_api_key.strip())
    return AgentStatusResponse(
        provider="google-gemini",
        model=settings.gemini_model,
        api_key_configured=key_configured,
        ai_enabled=settings.gemini_enabled,
        status="ready" if key_configured and settings.gemini_enabled else "not_configured",
    )
