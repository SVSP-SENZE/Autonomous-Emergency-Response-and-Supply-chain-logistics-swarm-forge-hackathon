"""Shared mock helpers for AI orchestrator tests (no real Gemini calls)."""

from __future__ import annotations

from types import SimpleNamespace


class FakeCall:
    """Mimics `google.genai.types.FunctionCall`."""

    def __init__(self, name: str, args: dict | None = None) -> None:
        self.name = name
        self.args = dict(args or {})


class FakePart:
    """Mimics `google.genai.types.Part` (text XOR function call)."""

    def __init__(
        self,
        text: str | None = None,
        function_call: FakeCall | None = None,
        function_response: SimpleNamespace | None = None,
    ) -> None:
        self.text = text
        self.function_call = function_call
        self.function_response = function_response


class FakeResponse:
    """Mimics a `generate_content` response with one candidate."""

    def __init__(self, parts: list[FakePart]) -> None:
        content = SimpleNamespace(parts=parts)
        self.candidates = [SimpleNamespace(content=content, finish_reason=None)]


def function_call_response(name: str, args: dict | None = None) -> FakeResponse:
    """A model turn that requests one tool call."""
    return FakeResponse([FakePart(function_call=FakeCall(name, args))])


def text_response(text: str) -> FakeResponse:
    """A final model turn with plain text."""
    return FakeResponse([FakePart(text=text)])


class FakeGeminiClient:
    """Scripted stand-in for `GeminiClient.generate_response`."""

    model = "gemini-3.8-flash"

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        # Every request payload the orchestrator sent us (for assertions).
        self.requests: list[list] = []
        self.last_config: object | None = None

    def generate_response(self, contents: list, config: object):
        self.requests.append(list(contents))
        self.last_config = config
        if not self.responses:
            raise AssertionError("FakeGeminiClient ran out of scripted responses")
        scripted = self.responses.pop(0)
        if isinstance(scripted, Exception):
            raise scripted
        return scripted

    @property
    def config(self) -> object | None:
        return getattr(self, "_last_config", None)
