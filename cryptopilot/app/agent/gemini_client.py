"""GeminiClient — lớp adapter cô lập SDK google-genai khỏi phần còn lại của Agent.

Vì sao tách:
  - Orchestrator (vòng ReAct) chỉ làm việc với kiểu provider-agnostic (AgentResponse,
    AgentToolCall, "turns" dạng dict) → đổi LLM provider sau này chỉ viết client mới.
  - Test orchestrator bằng FakeClient, KHÔNG cần gọi Gemini thật / cài SDK.

"turns" là biểu diễn hội thoại provider-agnostic, mỗi turn là một dict:
  {"role": "user",  "text": "..."}                         ← user nói
  {"role": "model", "text": "..."}                         ← model trả lời text
  {"role": "model", "tool_call": {"name":..., "args":...}} ← model xin gọi tool
  {"role": "tool",  "name":..., "response": {...}}          ← kết quả tool ta đưa lại
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class AgentToolCall:
    name: str
    args: dict


@dataclass
class AgentResponse:
    text: str | None = None
    tool_calls: list[AgentToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    """Giao diện tối thiểu orchestrator cần — GeminiClient và FakeClient đều thoả."""

    @property
    def is_configured(self) -> bool: ...

    async def generate(
        self,
        *,
        system_instruction: str,
        turns: list[dict],
        tool_specs: list[dict],
    ) -> AgentResponse: ...


class GeminiClient:
    """Triển khai LLMClient bằng google-genai (gemini-2.5-flash)."""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self._client = None  # tạo lười (lazy) ở lần gọi đầu

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _ensure_client(self):
        if self._client is None:
            from google import genai  # import lười: module load không cần SDK

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    # ── convert spec provider-agnostic → kiểu google-genai ──
    @staticmethod
    def _build_tool(tool_specs: list[dict]):
        from google.genai import types

        decls = []
        for spec in tool_specs:
            params = spec.get("parameters") or {}
            props = params.get("properties") or {}
            parameters = None
            if props:
                parameters = types.Schema(
                    type=getattr(types.Type, "OBJECT"),
                    properties={
                        k: types.Schema(
                            type=getattr(
                                types.Type,
                                str(v.get("type", "string")).upper(),
                                types.Type.STRING,
                            ),
                            description=v.get("description"),
                        )
                        for k, v in props.items()
                    },
                    required=params.get("required") or None,
                )
            decls.append(
                types.FunctionDeclaration(
                    name=spec["name"],
                    description=spec.get("description", ""),
                    parameters=parameters,
                )
            )
        return types.Tool(function_declarations=decls)

    @staticmethod
    def _build_contents(turns: list[dict]):
        from google.genai import types

        contents = []
        for t in turns:
            role = t["role"]
            if role == "user" and "text" in t:
                contents.append(
                    types.Content(role="user", parts=[types.Part(text=t["text"])])
                )
            elif role == "model" and "text" in t:
                contents.append(
                    types.Content(role="model", parts=[types.Part(text=t["text"])])
                )
            elif role == "model" and "tool_call" in t:
                tc = t["tool_call"]
                contents.append(
                    types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                function_call=types.FunctionCall(
                                    name=tc["name"], args=tc.get("args") or {}
                                )
                            )
                        ],
                    )
                )
            elif role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=t["name"], response=t["response"]
                            )
                        ],
                    )
                )
        return contents

    async def generate(
        self,
        *,
        system_instruction: str,
        turns: list[dict],
        tool_specs: list[dict],
    ) -> AgentResponse:
        from google.genai import types

        client = self._ensure_client()
        tool = self._build_tool(tool_specs)
        contents = self._build_contents(turns)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[tool],
            # ta TỰ điều khiển vòng ReAct → tắt auto function calling của SDK
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )
        resp = await client.aio.models.generate_content(
            model=self.model, contents=contents, config=config
        )
        return self._normalize(resp)

    @staticmethod
    def _normalize(resp) -> AgentResponse:
        text_parts: list[str] = []
        tool_calls: list[AgentToolCall] = []
        candidates = getattr(resp, "candidates", None) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    tool_calls.append(
                        AgentToolCall(name=fc.name, args=dict(fc.args or {}))
                    )
                    continue
                txt = getattr(part, "text", None)
                if txt:
                    text_parts.append(txt)
        text = "\n".join(text_parts).strip() if text_parts else None
        return AgentResponse(text=text, tool_calls=tool_calls)
