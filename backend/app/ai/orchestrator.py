"""Manual Gemini function-calling loop (the orchestrator core).

Flow per operator message:

    Gemini model -> function call request -> validate name/args against the
    allowlist -> controlled dispatcher -> real ReliefMesh services/db ->
    function-response parts sent back to Gemini -> final text response.

Safeguards: max model/tool iterations, max total tool calls, structured tool
errors handed back to the model, per-request audit persistence in
AgentSession / AgentMessage / AgentRun / AgentToolExecution.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

import json
from app.ai.client import GeminiClient, GroqClient
from app.ai.prompts import SYSTEM_PROMPT
from app.ai.tools.declarations import DECLARATIONS
from app.ai.tools.dispatcher import execute_tool
from app.core.clock import utcnow
from app.core.config import settings
from app.core.exceptions import (
    AgentToolError,
    AiNotConfiguredError,
    AiQuotaError,
    AiUpstreamError,
    AppError,
)
from app.models import AgentMessage, AgentRun, AgentSession, AgentToolExecution

logger = logging.getLogger("reliefmesh.ai.orchestrator")


def _build_groq_tools() -> list[dict]:
    """Convert tool declarations into OpenAI-compatible tool format for Groq."""
    tools = []
    for d in DECLARATIONS:
        tools.append({
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d["description"],
                "parameters": d.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return tools


@dataclass
class ToolTrace:
    """API-facing record of one tool execution (result kept for the run view)."""

    tool_name: str
    status: str
    execution_time_ms: int
    summary: str
    arguments_json: dict = field(default_factory=dict)
    result_json: dict = field(default_factory=dict)


@dataclass
class AgentTurnResult:
    """Outcome of one orchestrator turn."""

    session_id: int
    run_id: int
    status: str
    assistant_message: str
    tool_trace: list[ToolTrace]
    created_at: Any
    model_name: str
    error_message: str | None = None


class OrchestratorRunError(AppError):
    """Turn aborted by loop limits / malformed model output (HTTP 502)."""

    status_code = 502
    code = "agent_run_failed"


def _response_parts(response: Any) -> list[Any]:
    """Extract candidate parts from an SDK or mock response object."""
    candidates = getattr(response, "candidates", None)
    if not candidates:
        feedback = getattr(response, "prompt_feedback", None)
        block = getattr(feedback, "block_reason", None) if feedback is not None else None
        if block:
            raise AiUpstreamError(
                "Gemini blocked the request under its safety policy.",
                details={"block_reason": str(block)},
            )
        raise AiUpstreamError("Gemini returned no candidates.")
    content = getattr(candidates[0], "content", None)
    parts = getattr(content, "parts", None) or []
    if not parts:
        finish = getattr(candidates[0], "finish_reason", None)
        if finish is not None and "STOP" not in str(finish) and "MAX_TOKENS" not in str(finish):
            raise AiUpstreamError(
                f"Gemini stopped the response early ({finish}).",
                details={"finish_reason": str(finish)},
            )
        raise AiUpstreamError("Gemini returned an empty response.")
    return list(parts)


def _call_of(part: Any) -> tuple[str, dict] | None:
    call = getattr(part, "function_call", None)
    if call is None:
        return None
    name = getattr(call, "name", None)
    if not name:
        return None
    args = getattr(call, "args", None)
    if args is None:
        args = {}
    if hasattr(args, "items"):
        args = dict(args)
    elif isinstance(args, str):  # defensive: JSON-encoded args
        import json

        try:
            args = json.loads(args)
        except ValueError:
            args = {"_raw": args[:200]}
    return str(name), args


def _text_of(part: Any) -> str:
    text = getattr(part, "text", None)
    return text if isinstance(text, str) else ""


def _title_from(message: str) -> str:
    cleaned = " ".join(message.split())
    return cleaned[:60] + ("…" if len(cleaned) > 60 else "")


def _recent_history(db: Session, session_id: int) -> list[tuple[str, str]]:
    """Bounded (role, content) history; never includes tool payloads."""
    window = settings.gemini_history_window
    if window <= 0:
        return []
    rows = (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.id.desc())
        .limit(window)
        .all()
    )
    return [(row.role, row.content) for row in reversed(rows)]


def _sdk_types() -> Any:
    from app.ai import client as client_module

    if client_module.genai_types is None:  # pragma: no cover - guarded in client
        raise AiNotConfiguredError("The google-genai SDK is not installed.")
    return client_module.genai_types


def _to_schema(value: Any) -> Any:
    """Convert a plain JSON-schema dict into a google.genai.types.Schema."""
    gi = _sdk_types()
    if isinstance(value, dict) and "type" in value:
        type_name = str(value["type"]).upper()
        type_name = {"OBJECT": "OBJECT", "STRING": "STRING", "INTEGER": "INTEGER",
                     "NUMBER": "NUMBER", "BOOLEAN": "BOOLEAN", "ARRAY": "ARRAY"}.get(
                         type_name, "OBJECT")
        properties = value.get("properties") or {}
        raw_enum = value.get("enum")
        # Gemini schema enums must be strings; validated values stay native
        # (Pydantic coerces them back at dispatch time).
        if raw_enum and not all(isinstance(item, str) for item in raw_enum):
            enum = [str(item) for item in raw_enum]
        else:
            enum = raw_enum
        return gi.Schema(
            type=gi.Type[type_name],
            description=value.get("description"),
            enum=enum,
            items=_to_schema(value["items"]) if "items" in value else None,
            properties={key: _to_schema(child) for key, child in properties.items()} or None,
            required=value.get("required"),
        )
    return None


def _build_generation_config() -> Any:
    gi = _sdk_types()
    declarations = []
    from app.ai.tools.registry import REGISTRY

    for spec in REGISTRY.values():
        declarations.append(
            gi.FunctionDeclaration(
                name=spec.name,
                description=spec.description,
                parameters=_to_schema(spec.parameters) or gi.Schema(type=gi.Type.OBJECT),
            )
        )
    return gi.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_output_tokens,
        tools=[gi.Tool(function_declarations=declarations)],
    )


def run_agent_turn(
    db: Session,
    message: str,
    session_id: int | None,
    ai_client: GroqClient | GeminiClient,
) -> AgentTurnResult:
    """Execute one full orchestrator turn with REAL tool execution."""
    model_name = ai_client.model

    # --- Session / user message / run scaffolding ---------------------------
    if session_id is not None:
        session = db.get(AgentSession, session_id)
        if session is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"Agent session {session_id} not found")
    else:
        session = AgentSession(session_title=_title_from(message))
        db.add(session)
        db.flush()

    user_message = AgentMessage(session_id=session.id, role="user", content=message)
    db.add(user_message)
    db.flush()

    run = AgentRun(
        session_id=session.id,
        user_message_id=user_message.id,
        status="running",
        model_name=model_name,
    )
    db.add(run)
    db.flush()
    # Commit immediately: the write lock is never held across a model call
    db.commit()

    tool_trace: list[ToolTrace] = []
    final_text: str | None = None
    error_message: str | None = None
    started = time.perf_counter()

    try:
        if isinstance(ai_client, GroqClient):
            turn_text, tool_trace = _execute_groq_loop(db, run, message, session.id, ai_client)
        else:
            turn_text, tool_trace = _execute_loop(db, run, message, session.id, ai_client)
        final_text = turn_text
    except (AiUpstreamError, AiQuotaError, OrchestratorRunError) as exc:
        error_message = f"{type(exc).__name__}: {exc.message}"
        run.status = "failed"
        run.error_message = error_message
        run.completed_at = utcnow()
        db.commit()
        raise

    # --- Persist the assistant response --------------------------------------
    assistant_message = AgentMessage(
        session_id=session.id, role="assistant", content=final_text
    )
    db.add(assistant_message)
    db.flush()
    run.status = "completed"
    run.final_response = final_text
    run.assistant_message_id = assistant_message.id
    run.tool_call_count = len(tool_trace)
    run.completed_at = utcnow()
    db.commit()
    logger.info(
        "Agent run %s completed in %sms with %s tool call(s)",
        run.id,
        int((time.perf_counter() - started) * 1000),
        len(tool_trace),
    )
    return AgentTurnResult(
        session_id=session.id,
        run_id=run.id,
        status="completed",
        assistant_message=final_text,
        tool_trace=tool_trace,
        created_at=run.completed_at,
        model_name=model_name,
    )


def _execute_groq_loop(
    db: Session,
    run: AgentRun,
    message: str,
    session_id: int,
    groq_client: GroqClient,
) -> tuple[str, list[ToolTrace]]:
    """Function-calling loop for Groq OpenAI-compatible chat API."""
    tools = _build_groq_tools()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    for role, content in _recent_history(db, session_id):
        role_mapped = "assistant" if role == "assistant" else "user"
        messages.append({"role": role_mapped, "content": content})
    messages.append({"role": "user", "content": message})

    tool_trace: list[ToolTrace] = []
    max_iterations = max(settings.gemini_max_tool_iterations, 1)
    max_calls = max(settings.gemini_max_tool_calls, 1)

    for iteration in range(1, max_iterations + 1):
        response = groq_client.chat_completion(messages=messages, tools=tools)
        choice = response.choices[0]
        choice_msg = choice.message
        tool_calls = getattr(choice_msg, "tool_calls", None) or []
        content = choice_msg.content or ""

        if not tool_calls:
            if not content.strip():
                raise AiUpstreamError("Groq returned neither a tool call nor text.")
            return content, tool_trace

        # Append assistant tool call message to history
        assistant_msg_dict: dict[str, Any] = {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        }
        messages.append(assistant_msg_dict)

        for tc in tool_calls:
            if len(tool_trace) >= max_calls:
                raise OrchestratorRunError(
                    f"Tool call budget exhausted ({max_calls} calls).",
                    details={"call_count": len(tool_trace)},
                )
            name = tc.function.name
            raw_args = tc.function.arguments
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                args = {}

            started = time.perf_counter()
            try:
                result, status, summary = execute_tool(db, name, args)
            except AgentToolError as exc:
                result = {
                    "status": "error",
                    "error": {"code": "agent_tool_error", "message": exc.message},
                }
                status, summary = "error", f"Rejected: {exc.message}"

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            trace = ToolTrace(
                tool_name=name,
                status=status,
                execution_time_ms=result.get("execution_time_ms", elapsed_ms) if isinstance(result, dict) else elapsed_ms,
                summary=summary,
                arguments_json=args,
                result_json=result if isinstance(result, dict) else {"raw": str(result)[:500]},
            )
            tool_trace.append(trace)
            run.tool_call_count = len(tool_trace)
            db.add(
                AgentToolExecution(
                    agent_run_id=run.id,
                    tool_name=name,
                    arguments_json=trace.arguments_json,
                    result_json=trace.result_json,
                    status=status,
                    result_summary=summary[:500],
                    execution_time_ms=elapsed_ms,
                )
            )
            db.flush()
            db.commit()

            if status == "success":
                payload = {"status": "success", "result": result}
            else:
                error_info = (
                    result.get("error") if isinstance(result, dict) else None
                ) or {"code": "tool_error", "message": "Tool failed."}
                payload = {"status": "error", "error": error_info}

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(payload, default=str),
            })

    raise OrchestratorRunError(
        f"Maximum tool iterations reached ({max_iterations}) without a final answer.",
        details={"max_iterations": max_iterations, "tool_calls": len(tool_trace)},
    )


def _execute_loop(
    db: Session,
    run: AgentRun,
    message: str,
    session_id: int,
    ai_client: GeminiClient,
) -> tuple[str, list[ToolTrace]]:
    """The manual function-calling loop. Never invents tool execution."""
    gi = _sdk_types()
    config = _build_generation_config()
    contents: list[Any] = []

    for role, content in _recent_history(db, session_id):
        role_mapped = "user" if role == "user" else "model"
        contents.append(gi.Content(role=role_mapped, parts=[gi.Part(text=content)]))
    contents.append(gi.Content(role="user", parts=[gi.Part(text=message)]))

    tool_trace: list[ToolTrace] = []
    max_iterations = max(settings.gemini_max_tool_iterations, 1)
    max_calls = max(settings.gemini_max_tool_calls, 1)
    picked_config: Any = None

    for iteration in range(1, max_iterations + 1):
        try:
            response = ai_client.generate_response(contents, picked_config or config)
        except (AiUpstreamError, AiQuotaError, AiNotConfiguredError):
            raise
        except Exception as exc:  # unexpected SDK failure
            raise AiUpstreamError(
                "Gemini request failed unexpectedly.", details={"type": type(exc).__name__}
            ) from exc

        parts = _response_parts(response)
        calls = [call for call in (_call_of(part) for part in parts) if call is not None]
        model_text = "\n".join(text for text in (_text_of(part) for part in parts) if text)

        if not calls:
            if not model_text.strip():
                raise AiUpstreamError("Gemini returned neither a tool call nor text.")
            return model_text, tool_trace

        contents.append(response.candidates[0].content)
        function_parts = []
        for name, args in calls:
            if len(tool_trace) >= max_calls:
                raise OrchestratorRunError(
                    f"Tool call budget exhausted ({max_calls} calls).",
                    details={"call_count": len(tool_trace)},
                )
            started = time.perf_counter()
            try:
                result, status, summary = execute_tool(db, name, args)
            except AgentToolError as exc:
                result = {
                    "status": "error",
                    "error": {"code": "agent_tool_error", "message": exc.message},
                }
                status, summary = "error", f"Rejected: {exc.message}"
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            trace = ToolTrace(
                tool_name=name,
                status=status,
                execution_time_ms=result.get("execution_time_ms", elapsed_ms) if isinstance(result, dict) else elapsed_ms,
                summary=summary,
                arguments_json=args,
                result_json=result if isinstance(result, dict) else {"raw": str(result)[:500]},
            )
            tool_trace.append(trace)
            run.tool_call_count = len(tool_trace)  # accurate even on failure
            db.add(
                AgentToolExecution(
                    agent_run_id=run.id,
                    tool_name=name,
                    arguments_json=trace.arguments_json,
                    result_json=trace.result_json,
                    status=status,
                    result_summary=summary[:500],
                    execution_time_ms=elapsed_ms,
                )
            )
            db.flush()
            # Durable audit row + released write lock before the next model call.
            db.commit()
            if status == "success":
                payload: dict[str, Any] = {"status": "success", "result": result}
            else:
                error_info = (
                    result.get("error") if isinstance(result, dict) else None
                ) or {"code": "tool_error", "message": "Tool failed."}
                payload = {"status": "error", "error": error_info}
            function_parts.append(gi.Part.from_function_response(name=name, response=payload))
        contents.append(gi.Content(role="user", parts=function_parts))

    raise OrchestratorRunError(
        f"Maximum tool iterations reached ({max_iterations}) without a final answer.",
        details={"max_iterations": max_iterations, "tool_calls": len(tool_trace)},
    )
