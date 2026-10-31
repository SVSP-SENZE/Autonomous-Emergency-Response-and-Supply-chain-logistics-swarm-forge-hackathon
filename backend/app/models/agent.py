"""Agent conversation persistence: sessions, messages, runs, tool executions.

ReliefMesh uses integer primary keys everywhere; agent tables follow the same
convention. No API keys or sensitive data are ever stored here — only message
text, tool names, arguments, results, timings and statuses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.core.database import Base
from app.models.common import UTCDateTime


class AgentSession(Base):
    """One operator conversation with the AI orchestrator."""

    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    messages: Mapped[list["AgentMessage"]] = relationship(
        "AgentMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AgentMessage.id",
    )
    runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AgentRun.id",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<AgentSession {self.id} {self.session_title!r}>"


class AgentMessage(Base):
    """A single user or assistant message inside a session."""

    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')", name="ck_agent_messages_role"
        ),
        Index("ix_agent_messages_session", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    session: Mapped[AgentSession] = relationship("AgentSession", back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<AgentMessage {self.id} session={self.session_id} {self.role}>"


class AgentRun(Base):
    """One orchestrator execution: user message in, assistant response out."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="ck_agent_runs_status"
        ),
        Index("ix_agent_runs_session", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_message_id: Mapped[int] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    session: Mapped[AgentSession] = relationship("AgentSession", back_populates="runs")
    tool_executions: Mapped[list["AgentToolExecution"]] = relationship(
        "AgentToolExecution",
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AgentToolExecution.id",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<AgentRun {self.id} session={self.session_id} {self.status}>"


class AgentToolExecution(Base):
    """One tool invocation belonging to an agent run (audit trail)."""

    __tablename__ = "agent_tool_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'error')", name="ck_agent_tool_executions_status"
        ),
        Index("ix_agent_tool_executions_run", "agent_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    execution_time_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    run: Mapped[AgentRun] = relationship("AgentRun", back_populates="tool_executions")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<AgentToolExecution {self.id} run={self.agent_run_id} {self.tool_name} {self.status}>"
