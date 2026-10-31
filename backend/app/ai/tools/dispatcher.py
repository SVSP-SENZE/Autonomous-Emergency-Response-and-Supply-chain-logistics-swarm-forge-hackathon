"""Tool execution safety boundary.

`execute_tool` lives in `registry.py` alongside the allowlist; this dispatcher
module re-exports it as the single sanctioned entry point for the
orchestrator, keeping the safety-critical pieces together.
"""

from __future__ import annotations

from app.ai.tools.registry import REGISTRY, ToolSpec, execute_tool

__all__ = ["REGISTRY", "ToolSpec", "execute_tool"]
