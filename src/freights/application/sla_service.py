# src/freights/application/sla_service.py
"""SLA Service for FreightOperation.

Calculates SLA state deterministically from real timestamps stored in FreightOperation
and the planned time windows from FreightStop (scheduled_date + window_start/window_end).

Rules:
  - sla_state is NEVER persisted; always computed on demand.
  - Only real timestamps are used: assigned_at, started_at, completed_at, eta, delay_minutes
    from FreightOperation; scheduled_date + window_start/window_end from FreightStop.
  - No artificial ETAs are generated.
  - If there is insufficient data to determine an SLA state, returns SLAState.UNKNOWN.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from src.freights.infrastructure.django.models import FreightOperation


class SLAState(StrEnum):
    """Deterministic SLA classification for a freight operation."""

    ON_TIME = "ON_TIME"          # Operation is within the planned time window.
    AT_RISK = "AT_RISK"          # Operation is approaching the window limit.
    DELAYED = "DELAYED"          # Operation has exceeded the planned window.
    UNKNOWN = "UNKNOWN"          # Not enough data to determine SLA state.
    COMPLETED_ON_TIME = "COMPLETED_ON_TIME"  # Delivered within the planned window.
    COMPLETED_LATE = "COMPLETED_LATE"        # Delivered after the planned window.


@dataclass(frozen=True)
class SLAResult:
    """Result of an SLA computation."""

    state: SLAState
    # Planned deadline (datetime) derived from stop scheduled_date + window_end.
    # None when no delivery stop with a full time window exists.
    planned_deadline: datetime.datetime | None = None
    # Delay in minutes (positive = late, negative = early, None = unknown).
    computed_delay_minutes: int | None = None


class SLAService:
    """Computes SLA state for a FreightOperation without persisting anything.

    Usage:
        result = SLAService.compute(operation)
        if result.state == SLAState.DELAYED:
            ...

    The service prefers an explicit `eta` and `delay_minutes` set by backoffice.
    When those are absent it falls back to comparing real completion timestamps
    against the planned window of the delivery FreightStop.
    """

    # Operations approaching deadline within this threshold are flagged AT_RISK.
    AT_RISK_THRESHOLD_MINUTES: int = 30

    @classmethod
    def compute(cls, operation: FreightOperation) -> SLAResult:
        """Compute SLA for the given operation.

        Priority order for data sources:
        1. explicit delay_minutes set by backoffice.
        2. explicit eta compared to planned delivery window.
        3. completed_at vs planned delivery window (for completed operations).
        4. started_at vs planned delivery window (for in-progress operations).
        5. UNKNOWN when no data is available.
        """
        planned_deadline = cls._planned_deadline(operation)
        now = timezone.now()

        # ── 1. Explicit delay_minutes set by backoffice ───────────────────────
        if operation.delay_minutes is not None:
            if operation.delay_minutes <= 0:
                return SLAResult(
                    state=SLAState.ON_TIME,
                    planned_deadline=planned_deadline,
                    computed_delay_minutes=operation.delay_minutes,
                )
            return SLAResult(
                state=SLAState.DELAYED,
                planned_deadline=planned_deadline,
                computed_delay_minutes=operation.delay_minutes,
            )

        # ── 2. Explicit ETA vs planned deadline ───────────────────────────────
        if operation.eta is not None and planned_deadline is not None:
            delay = _minutes_between(planned_deadline, operation.eta)
            if delay <= 0:
                state = SLAState.ON_TIME
            elif delay <= cls.AT_RISK_THRESHOLD_MINUTES:
                state = SLAState.AT_RISK
            else:
                state = SLAState.DELAYED
            return SLAResult(
                state=state,
                planned_deadline=planned_deadline,
                computed_delay_minutes=delay if delay > 0 else None,
            )

        # ── 3. Completed operations: compare completed_at vs planned deadline ─
        if operation.completed_at is not None and planned_deadline is not None:
            delay = _minutes_between(planned_deadline, operation.completed_at)
            state = (
                SLAState.COMPLETED_ON_TIME if delay <= 0 else SLAState.COMPLETED_LATE
            )
            return SLAResult(
                state=state,
                planned_deadline=planned_deadline,
                computed_delay_minutes=delay if delay > 0 else None,
            )

        # ── 4. In-progress: compare now vs planned deadline ───────────────────
        if planned_deadline is not None:
            delay = _minutes_between(planned_deadline, now)
            if delay <= 0:
                state = SLAState.ON_TIME
            elif delay <= cls.AT_RISK_THRESHOLD_MINUTES:
                state = SLAState.AT_RISK
            else:
                state = SLAState.DELAYED
            return SLAResult(
                state=state,
                planned_deadline=planned_deadline,
                computed_delay_minutes=delay if delay > 0 else None,
            )

        # ── 5. Not enough data ────────────────────────────────────────────────
        return SLAResult(state=SLAState.UNKNOWN)

    @staticmethod
    def _planned_deadline(operation: FreightOperation) -> datetime.datetime | None:
        """Return the planned deadline datetime for the operation's delivery stop.

        Derived from FreightOperationStop.scheduled_date + FreightOperationStop.window_end
        of the last DELIVERY stop in the operation's stops.
        Returns None when this information is not available.
        """
        from src.freights.domain.enums import FreightStopType

        # Check if stops is prefetched on operation
        prefetched_cache = getattr(operation, "_prefetched_objects_cache", None)
        if isinstance(prefetched_cache, dict) and "stops" in prefetched_cache:
            stops = list(operation.stops.all())
            delivery_stops = [s for s in stops if s.stop_type == FreightStopType.DELIVERY]
            if not delivery_stops:
                return None
            delivery_stops.sort(key=lambda s: s.sequence, reverse=True)
            delivery_stop = delivery_stops[0]
        else:
            delivery_stop = (
                operation.stops
                .filter(stop_type=FreightStopType.DELIVERY)
                .order_by("-sequence")
                .first()
            )
        if delivery_stop is None:
            return None

        if delivery_stop.scheduled_date is None or delivery_stop.window_end is None:
            return None

        # Combine date + time, make it timezone-aware.
        naive_dt = datetime.datetime.combine(
            delivery_stop.scheduled_date, delivery_stop.window_end
        )
        # Use the server's current timezone (settings.TIME_ZONE via Django).
        return timezone.make_aware(naive_dt, timezone.get_current_timezone())


def _minutes_between(deadline: datetime.datetime, actual: datetime.datetime) -> int:
    """Return how many minutes `actual` is past `deadline`.

    Positive = late; negative = early.
    Uses round() to avoid microsecond-level truncation issues.
    """
    delta = actual - deadline
    return round(delta.total_seconds() / 60)
