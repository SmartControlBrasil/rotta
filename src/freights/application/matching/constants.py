MATCHING_ALGORITHM_VERSION = "v2.1"

MATCHING_WEIGHTS: dict[str, float] = {
    "distance": 0.15,
    "compliance": 0.20,
    "vehicle": 0.15,
    "cargo": 0.10,
    "temperature": 0.15,
    "availability": 0.15,
    "performance": 0.05,
    "price": 0.05,
}

NEUTRAL_SCORE_WHEN_UNAVAILABLE = 50.0

ROUTE_INTENT_BONUS_EXACT = 5.0
ROUTE_INTENT_BONUS_PARTIAL = 2.5
