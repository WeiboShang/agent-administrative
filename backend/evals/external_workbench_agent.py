"""Isolated native-tool agent loop for the external-method comparison.

Adapted from WorkBench ``run_agent_structured`` at pinned commit
49c7dfd00c03d384ec59ea57374f50b766aa5613 (MIT; attribution in
``docs/licenses/WORKBENCH-MIT.txt``).  The local adapter keeps the native tool-call
conversation, ordered execution, trace, iteration limit and autonomous setting while using
OpenRouter's OpenAI-compatible provider path.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

load_dotenv()

WORKBENCH_UPSTREAM_COMMIT = "49c7dfd00c03d384ec59ea57374f50b766aa5613"
MODEL = "openai/gpt-oss-120b"
PROVIDER = "openrouter"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TEMPERATURE = 0
REASONING_EFFORT = "low"
MAX_ITERATIONS = 20
MAX_EXECUTION_SECONDS = 600.0
STOPPED_MESSAGE = "Agent stopped due to iteration limit or time limit."
AUTONOMOUS_SUFFIX = (
    "Do not ask for confirmation before executing actions. "
    "Execute actions immediately and continue until the task is fully complete. "
    "Do not stop after a search or lookup step."
)
SYSTEM_PROMPT_TEMPLATE = (
    "Today's date is {weekday}, {date} and the current time is {time}. Remember the "
    "current date and time when completing tasks. Meetings must not start before 9am or "
    "end after 6pm. This is an isolated synthetic evaluation workspace. "
    + AUTONOMOUS_SUFFIX
)


def build_system_prompt(now: datetime) -> str:
    """Return the exact frozen prompt populated only with the visible case clock."""
    return SYSTEM_PROMPT_TEMPLATE.format(
        weekday=now.strftime("%A"),
        date=now.date().isoformat(),
        time=now.time().replace(microsecond=0).isoformat(),
    )


@dataclass(frozen=True)
class ExternalTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ModelTurn:
    content: str
    tool_calls: list[dict[str, Any]]
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class NativeToolProvider(Protocol):
    name: str
    model: str

    def invoke(
        self,
        *,
        system_prompt: str,
        messages: list[Any],
        tool_schemas: list[dict[str, Any]],
    ) -> ModelTurn: ...


class OpenRouterNativeToolProvider:
    """Native function calling through OpenRouter's OpenAI-compatible API."""

    name = PROVIDER
    model = MODEL

    def invoke(
        self,
        *,
        system_prompt: str,
        messages: list[Any],
        tool_schemas: list[dict[str, Any]],
    ) -> ModelTurn:
        llm = ChatOpenAI(
            model=self.model,
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=OPENROUTER_BASE_URL,
            temperature=TEMPERATURE,
            reasoning_effort=REASONING_EFFORT,
        )
        bound = llm.bind_tools(tool_schemas)
        response = bound.invoke([SystemMessage(content=system_prompt), *messages])
        usage = response.usage_metadata or {}
        return ModelTurn(
            content=str(response.content or ""),
            tool_calls=[dict(call) for call in response.tool_calls],
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            finish_reason=response.response_metadata.get("finish_reason"),
            raw_metadata={
                "finish_reason": response.response_metadata.get("finish_reason"),
                "model_name": response.response_metadata.get("model_name"),
                "usage_metadata": usage,
            },
        )


@dataclass
class TraceStep:
    iteration: int
    model_input: list[dict[str, Any]]
    model_content: str
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    usage: dict[str, int]
    finish_reason: str | None
    elapsed_seconds: float


@dataclass
class AgentResult:
    output: str
    stop_reason: str
    trace: list[TraceStep]
    tool_calls: list[dict[str, Any]]
    model_turns: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    runtime_seconds: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _message_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": message.content}
    if isinstance(message, AIMessage):
        return {
            "role": "assistant",
            "content": message.content,
            "tool_calls": message.tool_calls,
        }
    if isinstance(message, ToolMessage):
        return {
            "role": "tool",
            "content": message.content,
            "tool_call_id": message.tool_call_id,
        }
    return {"role": type(message).__name__, "content": str(message)}


def run_agent_structured(
    *,
    provider: NativeToolProvider,
    tools: list[ExternalTool],
    task: str,
    now: datetime,
    max_iterations: int = MAX_ITERATIONS,
    max_execution_seconds: float = MAX_EXECUTION_SECONDS,
) -> AgentResult:
    """Run the contemporary WorkBench-style native tool loop."""
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")
    if max_execution_seconds <= 0:
        raise ValueError("max_execution_seconds must be positive")
    tool_map = {tool.name: tool for tool in tools}
    if len(tool_map) != len(tools):
        raise ValueError("tool names must be unique")

    schemas = [tool.openai_schema() for tool in tools]
    prompt = build_system_prompt(now)
    messages: list[Any] = [HumanMessage(content=task)]
    trace: list[TraceStep] = []
    all_calls: list[dict[str, Any]] = []
    input_tokens = output_tokens = total_tokens = 0
    started = time.monotonic()

    for iteration in range(1, max_iterations + 1):
        elapsed = time.monotonic() - started
        if elapsed > max_execution_seconds:
            return AgentResult(
                output=STOPPED_MESSAGE,
                stop_reason="timeout",
                trace=trace,
                tool_calls=all_calls,
                model_turns=len(trace),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                runtime_seconds=elapsed,
                error=STOPPED_MESSAGE,
            )

        model_input = [_message_dict(message) for message in messages]
        turn = provider.invoke(
            system_prompt=prompt,
            messages=messages,
            tool_schemas=schemas,
        )
        input_tokens += turn.input_tokens
        output_tokens += turn.output_tokens
        total_tokens += turn.total_tokens

        if not turn.tool_calls:
            elapsed = time.monotonic() - started
            trace.append(
                TraceStep(
                    iteration=iteration,
                    model_input=model_input,
                    model_content=turn.content,
                    tool_calls=[],
                    tool_results=[],
                    usage={
                        "input_tokens": turn.input_tokens,
                        "output_tokens": turn.output_tokens,
                        "total_tokens": turn.total_tokens,
                    },
                    finish_reason=turn.finish_reason,
                    elapsed_seconds=elapsed,
                )
            )
            return AgentResult(
                output=turn.content,
                stop_reason="final_response",
                trace=trace,
                tool_calls=all_calls,
                model_turns=len(trace),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                runtime_seconds=elapsed,
            )

        assistant_calls: list[dict[str, Any]] = []
        for position, call in enumerate(turn.tool_calls):
            call_id = str(call.get("id") or f"call-{iteration}-{position}")
            assistant_calls.append(
                {
                    "name": str(call.get("name") or ""),
                    "args": dict(call.get("args") or {}),
                    "id": call_id,
                    "type": "tool_call",
                }
            )
        messages.append(AIMessage(content=turn.content, tool_calls=assistant_calls))

        tool_results: list[dict[str, Any]] = []
        for call in assistant_calls:
            name = call["name"]
            args = call["args"]
            tool = tool_map.get(name)
            if tool is None:
                observation = {
                    "ok": False,
                    "error": f"unknown tool {name!r}",
                    "available_tools": sorted(tool_map),
                }
            else:
                try:
                    observation = tool.handler(args)
                except (TypeError, ValueError, KeyError) as exc:
                    observation = {
                        "ok": False,
                        "error": type(exc).__name__,
                        "detail": str(exc),
                    }
            result = {
                "tool_call_id": call["id"],
                "name": name,
                "arguments": args,
                "observation": observation,
            }
            all_calls.append(result)
            tool_results.append(result)
            messages.append(
                ToolMessage(
                    content=json.dumps(observation, ensure_ascii=False, sort_keys=True),
                    tool_call_id=call["id"],
                )
            )

        trace.append(
            TraceStep(
                iteration=iteration,
                model_input=model_input,
                model_content=turn.content,
                tool_calls=assistant_calls,
                tool_results=tool_results,
                usage={
                    "input_tokens": turn.input_tokens,
                    "output_tokens": turn.output_tokens,
                    "total_tokens": turn.total_tokens,
                },
                finish_reason=turn.finish_reason,
                elapsed_seconds=time.monotonic() - started,
            )
        )

    elapsed = time.monotonic() - started
    return AgentResult(
        output=STOPPED_MESSAGE,
        stop_reason="iteration_limit",
        trace=trace,
        tool_calls=all_calls,
        model_turns=len(trace),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        runtime_seconds=elapsed,
        error=STOPPED_MESSAGE,
    )
