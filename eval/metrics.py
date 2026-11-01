"""인식 결과를 정답 라벨과 비교해 정확도를 계산한다."""

import re

import pandas as pd

from core.schema import Receipt

FIELDS = ("doc_type", "merchant_name", "paid_at", "total_amount")
CORE3 = ("merchant_name", "paid_at", "total_amount")
COMPANY_MARKERS = re.compile(r"\(주\)|㈜|주식회사")


def normalize_merchant(name: str | None) -> str:
    """법인 표기, 지점명, 공백, 문장부호를 지워서 비교한다. 예: '(주)이마트24 제주점' → '이마트24'."""
    if not name:
        return ""
    tokens = COMPANY_MARKERS.sub(" ", name).split()
    if len(tokens) >= 2 and tokens[-1].endswith("점"):
        tokens = tokens[:-1]
    return re.sub(r"[\W_]+", "", "".join(tokens)).lower()


def score_case(expected: dict, actual: Receipt | None) -> dict[str, bool]:
    """필드별 정답 여부와 core3(상호·일시·금액 모두 정답)를 돌려준다.

    영수증이 아닌 사진은 doc_type만 채점하고, 모든 키에 그 결과를 쓴다.
    """
    if actual is None:
        return {key: False for key in (*FIELDS, "core3")}
    doc_type_ok = actual.doc_type == expected["doc_type"]
    if expected["doc_type"] == "not_receipt":
        return {key: doc_type_ok for key in (*FIELDS, "core3")}
    scores = {
        "doc_type": doc_type_ok,
        "merchant_name": normalize_merchant(actual.merchant_name)
        == normalize_merchant(expected["merchant_name"]),
        "paid_at": actual.paid_at == expected["paid_at"],
        "total_amount": actual.total_amount == expected["total_amount"],
    }
    scores["core3"] = all(scores[key] for key in CORE3)
    return scores


def summarize(rows: list[dict]) -> pd.DataFrame:
    """source별 행과 'all' 행. 열은 필드별 정확도, core3, avg_seconds, error_rate, count."""
    df = pd.DataFrame(rows)
    df["has_error"] = df["error"].notna()

    def aggregate(group: pd.DataFrame) -> pd.Series:
        stats = {key: group[key].astype(float).mean() for key in (*FIELDS, "core3")}
        stats["avg_seconds"] = group["seconds"].mean()
        stats["error_rate"] = group["has_error"].mean()
        stats["count"] = len(group)
        return pd.Series(stats)

    by_source = {source: aggregate(group) for source, group in df.groupby("source")}
    by_source["all"] = aggregate(df)
    return pd.DataFrame(by_source).T
