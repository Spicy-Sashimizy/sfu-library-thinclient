"""Hot/cold scheduling decision core — PURE, no I/O, fully unit-testable.

This is the budget-safety heart of the broker. Keeping it side-effect-free means
the destroy/boot logic that protects the $200 credit can be tested exhaustively
(see test_scheduler.py) without ever touching the DigitalOcean API or a clock.

Policy (owner request 2026-06-19):
  * Weekday 09:00-17:00 (local tz): droplet stays HOT — instant page load, the
    idle reaper is suppressed so a quiet lunch hour never tears it down.
  * Pre-warm: boot `prewarm_minutes` before the window opens so 09:00 is ready.
  * Outside the window: scale-to-zero. The droplet only runs if an after-hours
    /start click woke it, and the idle reaper destroys it after `idle_minutes`.
  * Hard daily killswitch (highest priority): if cumulative runtime today exceeds
    `max_runtime_hours_per_day`, destroy regardless of state — the backstop
    against a stuck reaper pinning spend.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime


class DropletStatus(str, enum.Enum):
    DOWN = "down"
    BOOTING = "booting"
    UP = "up"


class Action(str, enum.Enum):
    NONE = "none"
    BOOT = "boot"
    DESTROY = "destroy"


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str


@dataclass
class BrokerState:
    status: DropletStatus = DropletStatus.DOWN
    idle_minutes: float | None = None
    runtime_hours_today: float = 0.0
    on_demand_session: bool = False
    runtime_hours_month: float = 0.0
    session_minutes: float | None = None


def in_business_window(now: datetime, *, start_hour: int, end_hour: int,
                       business_days: frozenset[int], prewarm_minutes: int = 0) -> bool:
    """True if `now` (tz-aware, local) is inside the hot window, pre-warm included.

    Pre-warm extends the OPEN edge only: we boot a few minutes early so the
    window starts hot, but we still tear down exactly at `end_hour`.
    """
    if now.weekday() not in business_days:
        return False
    minute_of_day = now.hour * 60 + now.minute
    open_at = start_hour * 60 - max(0, prewarm_minutes)
    close_at = end_hour * 60
    return open_at <= minute_of_day < close_at


def month_cap_reached(state: BrokerState, cfg) -> bool:
    """True once this calendar month's runtime hits the monthly cap (0 = no cap)."""
    cap = getattr(cfg, "max_runtime_hours_per_month", 0) or 0
    return cap > 0 and state.runtime_hours_month >= cap


def budget_exhausted(state: BrokerState, cfg) -> str:
    """Reason a wake must be refused (daily or monthly cap spent), else ''."""
    if month_cap_reached(state, cfg):
        return (f"monthly cap: {state.runtime_hours_month:.2f}h >= "
                f"{cfg.max_runtime_hours_per_month:.2f}h this month")
    if state.runtime_hours_today >= cfg.max_runtime_hours_per_day:
        return (f"daily cap: {state.runtime_hours_today:.2f}h >= "
                f"{cfg.max_runtime_hours_per_day:.2f}h today")
    return ""


def decide(now: datetime, state: BrokerState, cfg) -> Decision:
    """Return the action the scheduler tick should take. Pure function of inputs."""
    if state.status in (DropletStatus.UP, DropletStatus.BOOTING):
        if state.runtime_hours_today >= cfg.max_runtime_hours_per_day:
            return Decision(Action.DESTROY,
                            f"killswitch: {state.runtime_hours_today:.2f}h >= "
                            f"{cfg.max_runtime_hours_per_day:.2f}h daily cap")
        if month_cap_reached(state, cfg):
            return Decision(Action.DESTROY,
                            f"killswitch: {state.runtime_hours_month:.2f}h >= "
                            f"{cfg.max_runtime_hours_per_month:.2f}h monthly cap")

    hot = in_business_window(
        now,
        start_hour=cfg.business_start_hour,
        end_hour=cfg.business_end_hour,
        business_days=cfg.business_days,
        prewarm_minutes=cfg.prewarm_minutes,
    )

    if hot:
        if state.status == DropletStatus.DOWN:
            spent = budget_exhausted(state, cfg)
            if spent:
                return Decision(Action.NONE, f"business hours: staying down ({spent})")
            return Decision(Action.BOOT, "schedule: business-hours prewarm/keep-hot")
        return Decision(Action.NONE, "business hours: hot, idle reaper suppressed")

    if state.status in (DropletStatus.UP, DropletStatus.BOOTING):
        if not state.on_demand_session:
            return Decision(Action.DESTROY, "after-hours: no active on-demand session")
        limit = getattr(cfg, "max_session_minutes", 0) or 0
        if limit > 0 and state.session_minutes is not None and state.session_minutes >= limit:
            return Decision(Action.DESTROY,
                            f"session limit: {state.session_minutes:.1f}m since wake >= {limit}m")
        if state.idle_minutes is not None and state.idle_minutes >= cfg.idle_minutes:
            return Decision(Action.DESTROY,
                            f"after-hours idle reaper: idle {state.idle_minutes:.1f}m "
                            f">= {cfg.idle_minutes}m")
        return Decision(Action.NONE, "after-hours: on-demand session active")

    return Decision(Action.NONE, "after-hours: down, awaiting on-demand wake")
