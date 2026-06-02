"""LLM 추상화 레이어 (function-calling).

- OpenAIClient / AnthropicClient: 실제 API (키 있으면 사용)
- StubClient: 키 없이도 데모가 돌도록 규칙 기반으로 도구 호출을 흉내냄

에이전트 코어는 이 인터페이스(chat)만 의존하므로 백엔드 교체가 자유롭다.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)  # [{id,name,arguments}]


class BaseLLM:
    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        raise NotImplementedError


# ---------------------------------------------------------------
# OpenAI 백엔드
# ---------------------------------------------------------------
class OpenAIClient(BaseLLM):
    def __init__(self, model: str = "gpt-4o-mini"):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model

    def chat(self, messages, tools):
        resp = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, tool_choice="auto",
        )
        msg = resp.choices[0].message
        calls = []
        for tc in (msg.tool_calls or []):
            calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": json.loads(tc.function.arguments or "{}"),
            })
        return LLMResponse(content=msg.content, tool_calls=calls)


# ---------------------------------------------------------------
# Anthropic 백엔드
# ---------------------------------------------------------------
class AnthropicClient(BaseLLM):
    def __init__(self, model: str = "claude-3-5-sonnet-latest"):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model

    def chat(self, messages, tools):
        system = ""
        conv = []
        for m in messages:
            if m["role"] == "system":
                system += m["content"] + "\n"
            else:
                conv.append(m)
        a_tools = [{
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        } for t in tools]
        resp = self.client.messages.create(
            model=self.model, system=system, messages=conv,
            tools=a_tools, max_tokens=1024,
        )
        content, calls = None, []
        for block in resp.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                calls.append({"id": block.id, "name": block.name,
                              "arguments": block.input})
        return LLMResponse(content=content, tool_calls=calls)


# ---------------------------------------------------------------
# Stub 백엔드 (키 없이 데모/테스트)
# ---------------------------------------------------------------
class StubClient(BaseLLM):
    """간단한 규칙으로 도구 호출을 결정하고, 도구 결과를 받으면 요약한다.

    실제 LLM 추론을 대체하진 못하지만, 파이프라인 전체 흐름을 키 없이 검증 가능.
    """

    def chat(self, messages, tools):
        last = messages[-1]
        if last["role"] == "tool":
            results = [m for m in messages if m["role"] == "tool"]
            joined = "\n".join(m["content"][:400] for m in results)
            return LLMResponse(content=(
                "[STUB 응답] 수집된 근거 요약:\n" + joined +
                "\n\n(실제 배포 시 LLM이 이 근거로 자연어 답변을 생성합니다.)"
            ))
        user = next((m["content"] for m in reversed(messages)
                     if m["role"] == "user"), "")
        u = user.lower()
        if "코인" in user or "crypto" in u or "비트코인" in user:
            return LLMResponse(tool_calls=[{
                "id": "c1", "name": "list_assets",
                "arguments": {"asset_type": "CRYPTO"}}])
        if "섹터" in user or "반도체" in user:
            return LLMResponse(tool_calls=[{
                "id": "c1", "name": "graph_query",
                "arguments": {"cypher":
                    "MATCH (a:Asset)-[:ISSUED_BY]->(:Company)-[:IN_SECTOR]->(s:Sector) "
                    "RETURN a.symbol, a.name, s.name LIMIT 20"}}])
        return LLMResponse(tool_calls=[{
            "id": "c1", "name": "vector_search",
            "arguments": {"query": user, "k": 5}}])


def make_llm() -> BaseLLM:
    """환경에 따라 백엔드 자동 선택."""
    if os.getenv("OPENAI_API_KEY"):
        try:
            return OpenAIClient(os.getenv("AGENT_MODEL", "gpt-4o-mini"))
        except Exception:  # noqa: BLE001
            pass
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return AnthropicClient(os.getenv("AGENT_MODEL", "claude-3-5-sonnet-latest"))
        except Exception:  # noqa: BLE001
            pass
    print("[!] LLM API 키 없음 → StubClient 사용(데모 모드)")
    return StubClient()
