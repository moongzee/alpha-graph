"""온톨로지 스키마/시드 적재 스크립트.

사용:
    python ontology/load_schema.py            # 제약+온톨로지 메타 적재
    python ontology/load_schema.py --examples # 예시 데이터까지 적재

환경변수:
    NEO4J_URI       (기본 bolt://localhost:7687)
    NEO4J_USER      (기본 neo4j)
    NEO4J_PASSWORD  (기본 password)
"""
from __future__ import annotations
import os
import sys
import pathlib

try:
    from neo4j import GraphDatabase
except ImportError:
    sys.exit("neo4j 드라이버가 필요합니다:  pip install neo4j")

HERE = pathlib.Path(__file__).parent
SCHEMA = HERE / "schema"
EXAMPLES = HERE / "examples"


def split_statements(cypher_text: str) -> list[str]:
    """; 기준으로 분리하되 주석/공백 제거. (간단 파서)"""
    stmts = []
    for raw in cypher_text.split(";"):
        # 줄 단위로 // 주석 제거
        lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("//")]
        stmt = "\n".join(lines).strip()
        if stmt:
            stmts.append(stmt)
    return stmts


def run_file(session, path: pathlib.Path) -> int:
    text = path.read_text(encoding="utf-8")
    stmts = split_statements(text)
    for stmt in stmts:
        session.run(stmt)
    print(f"  [ok] {path.name}: {len(stmts)} statements")
    return len(stmts)


def main() -> None:
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pw = os.getenv("NEO4J_PASSWORD", "password")
    load_examples = "--examples" in sys.argv

    driver = GraphDatabase.driver(uri, auth=(user, pw))
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            print(f"[*] Neo4j 연결: {uri}")
            run_file(session, SCHEMA / "constraints.cypher")
            run_file(session, SCHEMA / "ontology.cypher")
            if load_examples:
                run_file(session, EXAMPLES / "sample_graph.cypher")
                print("[*] 예시 데이터 적재 완료")
        print("[done] 온톨로지 스키마 적재 완료")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
