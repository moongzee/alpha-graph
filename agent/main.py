"""에이전트 CLI 엔트리포인트.

사용:
    python agent/main.py "최근 1주일 호재 뉴스가 집중된 코인은?"
    python agent/main.py            # 인자 없으면 대화형 모드

환경변수:
    NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD  (없으면 그래프 미연결 스캐폴드 모드)
    PG_DSN                                    (없으면 시세 미연결)
    OPENAI_API_KEY 또는 ANTHROPIC_API_KEY     (없으면 StubClient 데모 모드)
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core.agent import Agent
from agent.core.llm import make_llm
from agent.tools.registry import ToolRegistry


def build_agent() -> Agent:
    driver = None
    embedder = None
    uri = os.getenv("NEO4J_URI")
    if uri:
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(
                uri,
                auth=(os.getenv("NEO4J_USER", "neo4j"),
                      os.getenv("NEO4J_PASSWORD", "password")),
            )
            driver.verify_connectivity()
            from pipeline.transform.enrich import Embedder
            embedder = Embedder()
            print(f"[*] Neo4j 연결: {uri}")
        except Exception as e:  # noqa: BLE001
            print(f"[!] Neo4j 연결 실패({e}) → 스캐폴드 모드")
            driver = None

    tools = ToolRegistry(neo4j_driver=driver, pg_dsn=os.getenv("PG_DSN"),
                         embedder=embedder)
    llm = make_llm()
    return Agent(llm, tools)


def main() -> None:
    agent = build_agent()

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(f"\n[질문] {question}\n")
        print(agent.run(question))
        return

    # 대화형
    print("금융 인텔리전스 에이전트 (종료: exit)")
    while True:
        try:
            q = input("\n질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"exit", "quit", "q", ""}:
            break
        print()
        print(agent.run(q))


if __name__ == "__main__":
    main()
