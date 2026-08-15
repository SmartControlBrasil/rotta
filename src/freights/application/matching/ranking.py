from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.freights.domain.matching_enums import MatchEligibilityStatus


@dataclass(frozen=True)
class RankedCandidate:
    candidate_index: int
    rank_position: int
    total_score: Decimal | None
    eligibility_status: MatchEligibilityStatus


def assign_rank_positions(
    *,
    candidates: list,
    score_attr: str = "total_score",
    eligibility_attr: str = "eligibility_status",
) -> list[RankedCandidate]:
    eligible = []
    ineligible = []
    for index, candidate in enumerate(candidates):
        status = getattr(candidate, eligibility_attr)
        score = getattr(candidate, score_attr)
        if status == MatchEligibilityStatus.ELIGIBLE.value:
            eligible.append((index, score))
        else:
            ineligible.append((index, score))

    eligible.sort(
        key=lambda item: (
            item[1] is None,
            -(float(item[1]) if item[1] is not None else 0.0),
            item[0],
        )
    )
    ineligible.sort(key=lambda item: item[0])

    ranked: list[RankedCandidate] = []
    position = 1
    for index, score in eligible:
        ranked.append(
            RankedCandidate(
                candidate_index=index,
                rank_position=position,
                total_score=score,
                eligibility_status=MatchEligibilityStatus.ELIGIBLE,
            )
        )
        position += 1
    for index, score in ineligible:
        ranked.append(
            RankedCandidate(
                candidate_index=index,
                rank_position=position,
                total_score=score,
                eligibility_status=MatchEligibilityStatus.INELIGIBLE,
            )
        )
        position += 1
    return ranked
