"""ReAct 에이전트 코어 루프.

흐름:
  1) system + user 메시지 구성
  2) LLM.chat(messages, tools) 호출
  3) tool_calls가 있으면 실행 → 결과를 tool 메시지로 추가 → 2)로 반복
  4) tool_calls가 없으면(=최종 답변) 면책 고지 부착 후 반환

안전장치:
  - 최대 반복 수 제한(무한루프 방지)
  - 모든 답변에 면책/기준시각 자동 삽입
"""
from __future__ import annotations
import datetime as dt
import json
import pathlib

PROMPT_DIR = pathlib.Path(__file__).parent.parent / "prompts"

DISCLAIMER = (
    "\n\n---\n[주의] 본 정보는 데이터 기반 참고용이며 투자 권유가 아닙니다. "
    "투자 판단과 책임은 본인에게 있습니다."
)


class Agent:
    def __init__(self, llm, tools, max_steps: int = 6):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.system_prompt = (PROMPT_DIR / "system.md").read_text(encoding="utf-8")

    def run(self, question: str, verbose: bool = True) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": question},
        ]
        tool_specs = self.tools.specs()

        for step in range(self.max_steps):
            resp = self.llm.chat(messages, tool_specs)

            if not resp.tool_calls:
                answer = resp.content or "근거가 충분하지 않아 답변을 생성하지 못했습니다."
                return self._finalize(answer)

            messages.append({
                "role": "assistant",
                "content": resp.content or "",
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"],
                                  "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                    for c in resp.tool_calls
                ],
            })

            for call in resp.tool_calls:
                if verbose:
                    print(f"  [step {step+1}] tool={call['name']} args={call['arguments']}")
                result = self.tools.call(call["name"], call["arguments"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        resp = self.llm.chat(messages, tool_specs)
        return self._finalize(resp.content or "분석을 완료하지 못했습니다(스텝 한도).")

    def _finalize(self, answer: str) -> str:
        as_of = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        if "투자 권유가 아닙니다" in answer:
            return answer
        return f"{answer}\n\n(데이터 기준: {as_of}){DISCLAIMER}"
