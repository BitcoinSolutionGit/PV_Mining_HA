from __future__ import annotations

from typing import Any, Dict, List

from services.power_planner import plan_and_allocate_auto


def dry_run_plan() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def _capture(msg: str) -> None:
        if msg.startswith("[DRY] "):
            rows.append({"line": msg})

    plan_and_allocate_auto(apply=False, dry_run=True, log=True, logger=_capture)
    return rows


def log_dry_run_plan(prefix: str = "[plan]") -> None:
    try:
        plan_and_allocate_auto(
            apply=False,
            dry_run=True,
            log=True,
            logger=lambda msg: print(f"{prefix} {msg}", flush=True),
        )
    except Exception as e:
        print(f"{prefix} error: {e}", flush=True)
