"""파이프라인 변환 모듈: 엔티티 해소 / 감성 / 임베딩.

설계 원칙: 모든 무거운 모델 호출은 인터페이스 뒤에 두고,
스캐폴드 단계에서는 규칙 기반 stub으로 동작하게 한다.
운영 시 stub을 실제 모델(FinBERT, 임베딩 API)로 교체.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------
# 엔티티 해소 (Entity Resolution)
# ---------------------------------------------------------------
@dataclass
class Mention:
    symbol: str
    market: str
    confidence: float


class EntityResolver:
    """assets 테이블의 별칭 사전을 사용해 뉴스 본문에서 자산을 링킹.

    운영 확장 포인트:
      - 사전 미스 시 NER + 임베딩 최근접으로 fallback
      - confidence 임계값 미만은 검수 큐로
    """

    def __init__(self, alias_index: dict[str, Mention] | None = None):
        # alias(소문자) -> Mention
        self.alias_index = alias_index or {}

    @classmethod
    def from_assets(cls, assets: list[dict]) -> "EntityResolver":
        idx: dict[str, Mention] = {}
        for a in assets:
            m = Mention(symbol=a["symbol"], market=a["market"], confidence=1.0)
            names = [a["symbol"], a["name"], *(a.get("aliases") or [])]
            for nm in names:
                if nm:
                    idx[nm.lower()] = m
        return cls(idx)

    def resolve(self, text: str) -> list[Mention]:
        if not text:
            return []
        hay = text.lower()
        hits: dict[tuple[str, str], Mention] = {}
        for alias, mention in self.alias_index.items():
            # 단어 경계 우선, 한글/심볼은 부분일치 허용
            if alias in hay:
                conf = mention.confidence
                # 짧은 별칭(2자 이하)은 오탐 위험 → 신뢰도 감점
                if len(alias) <= 2:
                    conf *= 0.6
                key = (mention.symbol, mention.market)
                if key not in hits or hits[key].confidence < conf:
                    hits[key] = Mention(mention.symbol, mention.market, round(conf, 3))
        return list(hits.values())


# ---------------------------------------------------------------
# 감성 분석 (Sentiment) - stub
# ---------------------------------------------------------------
@dataclass
class SentimentResult:
    label: str   # POS / NEG / NEU
    score: float
    model: str = "rule-stub"


_POS = ["급등", "호재", "수혜", "최대", "신고가", "유입", "양산", "흑자", "상승", "돌파", "surge", "rally", "beat"]
_NEG = ["급락", "악재", "하락", "손실", "적자", "규제", "해킹", "유출", "리콜", "폭락", "plunge", "hack", "miss"]


class SentimentAnalyzer:
    """운영 시 FinBERT 등으로 교체. 지금은 키워드 가중합 stub."""

    def analyze(self, text: str) -> SentimentResult:
        if not text:
            return SentimentResult("NEU", 0.0)
        t = text.lower()
        pos = sum(t.count(w.lower()) for w in _POS)
        neg = sum(t.count(w.lower()) for w in _NEG)
        if pos == neg:
            return SentimentResult("NEU", 0.0)
        if pos > neg:
            return SentimentResult("POS", round(min(1.0, 0.5 + 0.1 * (pos - neg)), 3))
        return SentimentResult("NEG", round(-min(1.0, 0.5 + 0.1 * (neg - pos)), 3))


# ---------------------------------------------------------------
# 임베딩 (Embedding) - stub
# ---------------------------------------------------------------
class Embedder:
    """운영 시 임베딩 API/로컬 모델로 교체. 지금은 결정적 해시 벡터 stub."""

    def __init__(self, dim: int = 1536):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        import hashlib
        import struct
        vec = [0.0] * self.dim
        if not text:
            return vec
        for token in re.findall(r"\w+", text.lower()):
            h = hashlib.md5(token.encode()).digest()
            idx = struct.unpack("<I", h[:4])[0] % self.dim
            vec[idx] += 1.0
        # L2 정규화
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [round(x / norm, 6) for x in vec]
