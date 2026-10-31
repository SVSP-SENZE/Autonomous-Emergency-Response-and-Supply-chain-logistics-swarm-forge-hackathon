"""Agent API schemas (chat + run/session/state views)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentChatRequest(BaseModel):
    """`POST /agent/chat` request body."""

    model_config = ConfigDict(extra="forbid")

    session_id: int | None = None
    message: str = Field(min_length=1, max_length=4000)


class ToolCallTrace(BaseModel):
    """One tool execution as surfaced to the operator (no result payload)."""

    tool_name: str
    status: Literal["success", "error"]
    execution_time_ms: int = 0
    summary: str


class AgentChatResponse(BaseModel):
    """`POST /agent/chat` response."""

    data_mode: Literal["SIMULATED"] = "SIMULATED"
    session_id: int
    run_id: int
    status: Literal["completed", "failed"]
    assistant_message: str
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    created_at: datetime


class AgentSessionSummary(BaseModel):
    """`GET /agent/sessions` item."""

    session_id: int
    session_title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class AgentMessageView(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime


class AgentRunSummary(BaseModel):
    """`AgentRun` summary for session history (safe trace, no payloads)."""

    run_id: int
    status: Literal["running", "completed", "failed"]
    model_name: str
    tool_call_count: int
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AgentSessionDetail(BaseModel):
    """`GET /agent/sessions/{session_id}` response."""

    session_id: int
    session_title: str
    created_at: datetime
    updated_at: datetime
    messages: list[AgentMessageView]
    runs: list[AgentRunSummary] = Field(default_factory=list)


class AgentToolExecutionView(BaseModel):
    tool_name: str
    status: Literal["success", "error"]
    arguments_json: dict = Field(default_factory=dict)
    result_json: dict = Field(default_factory=dict)
    result_summary: str | None = None
    execution_time_ms: int = 0
    created_at: datetime


class AgentRunDetail(BaseModel):
    """`GET /agent/runs/{run_id}` response."""

    run_id: int
    session_id: int
    status: Literal["running", "completed", "failed"]
    model_name: str
    user_message: str
    assistant_message: str | None
    tool_call_count: int
    tool_executions: list[AgentToolExecutionView]
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class AgentStatusResponse(BaseModel):
    """`GET /agent/status` response (never contains the API key)."""

    provider: Literal["google-gemini"]
    model: str
    api_key_configured: bool
    ai_enabled: bool
    status: Literal["ready", "not_configured"]
    data_mode: Literal["SIMULATED"] = "SIMULATED"
