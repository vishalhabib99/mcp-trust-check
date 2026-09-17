"""Live counterpart to what `action.yml`/`combine.py` already do for the
batch/static case: run mcp-doctor's checks always, mcp-fuzz's and
mcp-reality-check's on every real call — but for an agent's actual
session, not a CI run.

`GuardedSession` wraps a real `ClientSession` and composes all three
trilogy tools' live gates at their natural point: mcp-doctor's
registration checks once at discovery (`list_tools`), mcp-fuzz's latency/
size gate and mcp-reality-check's correctness checks together on every
real call (`call_tool`) — **one** real network call per tool call, not
three, by construction. `mcp_fuzz.gate.guarded_call` and `mcp_reality_
check.gate.LatencyGate.timed_call` (well, the reverse — see each
package's own gate module) each make their own call-and-check round
trip; calling both here would mean two real network calls per logical
call, which for a non-idempotent or destructive tool isn't just
wasteful, it's actively wrong. Instead, this makes the call exactly once
and fans the one real response out to each sibling package's own already-
pure, already-tested per-response functions (`LatencyGate.record`,
`mcp_reality_check.checks.*`) — the same functions their own wrappers
call internally, reused here instead of duplicated.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from mcp import ClientSession, types

from mcp_doctor.gate import RegistrationResult, check_tool_registration
from mcp_fuzz.gate import LatencyGate
from mcp_reality_check.checks import (
    check_echo_mismatch,
    check_empty_content,
    check_output_schema,
    check_refusal_in_disguise,
    response_text_from_content,
)
from mcp_reality_check.generator import string_argument_values

DEFAULT_TIMEOUT_SECONDS = 15.0


def _field(model, snake_name: str, camel_name: str):
    """Same cross-`mcp`-version compat helper duplicated in each sibling
    package — kept local rather than imported from one of them, since none
    of the three treats it as public API."""
    if hasattr(model, snake_name):
        return getattr(model, snake_name)
    return getattr(model, camel_name)


@dataclass
class GuardedCallResult:
    tool_name: str
    # "ok" | "crash" | "timeout"
    outcome: str
    detail: str = ""
    is_error: bool = False
    response_text: str = ""
    duration_ms: float = 0.0
    response_chars: int = 0
    # correctness (mcp-reality-check)
    refusal_in_disguise: str | None = None
    empty_content: bool = False
    schema_violation: str | None = None
    echo_mismatch_inputs: list[str] | None = None
    # latency/size (mcp-fuzz)
    slow_reasons: list[str] = field(default_factory=list)
    bloated_reasons: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(
            self.refusal_in_disguise or self.empty_content or self.schema_violation
            or self.slow_reasons or self.bloated_reasons
        )


class GuardedSession:
    """One `ClientSession` per instance — `LatencyGate`'s per-tool history
    accumulates across every `call_tool` made through this wrapper, same
    as using `mcp_fuzz.gate.LatencyGate` directly."""

    def __init__(self, session: ClientSession):
        self._session = session
        self._latency_gate = LatencyGate()
        self._tools_by_name: dict[str, types.Tool] = {}
        self.registration_results: dict[str, RegistrationResult] = {}

    async def list_tools(self):
        """Calls the real `tools/list` and runs mcp-doctor's registration
        checks on every tool once, at discovery — before any tool is ever
        called. Results are cached on `.registration_results`, keyed by
        tool name, and reused by `call_tool` below for output-schema
        checking without needing a second `tools/list` round trip."""
        result = await self._session.list_tools()
        self._tools_by_name = {t.name: t for t in result.tools}
        self.registration_results = {
            t.name: check_tool_registration(t.name, t.description, t.annotations)
            for t in result.tools
        }
        return result

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> GuardedCallResult:
        """Calls `tool_name` via the wrapped session exactly once, and
        checks the one real response for both latency/size (mcp-fuzz) and
        correctness (mcp-reality-check) issues. Use in place of a bare
        `session.call_tool(...)`."""
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments), timeout=timeout
            )
        except asyncio.TimeoutError:
            return GuardedCallResult(tool_name, "timeout", detail=f"no response within {timeout}s")
        except Exception as exc:
            return GuardedCallResult(tool_name, "crash", detail=f"{type(exc).__name__}: {exc}")
        duration_ms = (time.monotonic() - started) * 1000

        is_error = bool(_field(result, "is_error", "isError")) if isinstance(result, types.CallToolResult) else False
        response_text = response_text_from_content(result.content) if hasattr(result, "content") else ""

        guarded = GuardedCallResult(
            tool_name, "ok", is_error=is_error, response_text=response_text,
            duration_ms=duration_ms, response_chars=len(response_text),
        )

        latency_result = self._latency_gate.record(tool_name, duration_ms, len(response_text))
        guarded.slow_reasons = latency_result.slow_reasons
        guarded.bloated_reasons = latency_result.bloated_reasons

        if not is_error:
            guarded.refusal_in_disguise = check_refusal_in_disguise(response_text)
            guarded.empty_content = check_empty_content(response_text)
            guarded.echo_mismatch_inputs = check_echo_mismatch(response_text, string_argument_values(arguments))

            tool = self._tools_by_name.get(tool_name)
            if tool is not None:
                output_schema = _field(tool, "output_schema", "outputSchema")
                structured = _field(result, "structured_content", "structuredContent")
                guarded.schema_violation = check_output_schema(structured, output_schema)

        return guarded
