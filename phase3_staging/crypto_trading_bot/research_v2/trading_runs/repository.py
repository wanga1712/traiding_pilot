"""TradingRunRepository — UI reads runs through this abstraction only."""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .fixtures import ALL_FIXTURES
from .schema import validate_run_or_raise


class TradingRunRepository(ABC):
    @abstractmethod
    def list_runs(self) -> list[dict[str, Any]]:
        """Return lightweight run index rows."""

    @abstractmethod
    def get_run(self, run_id: str) -> dict[str, Any] | None:
        pass

    def get_summary(self, run_id: str) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if not run:
            return None
        return {
            "run_id": run["run_id"],
            "run_status": run["run_status"],
            "created_at": run.get("created_at"),
            "strategy": run.get("strategy"),
            "market": run.get("market"),
            "capital": run.get("capital"),
            "performance": run.get("performance"),
            "execution": run.get("execution"),
            "research_metrics": run.get("research_metrics"),
        }

    def get_equity_curve(self, run_id: str) -> list[dict[str, Any]] | None:
        run = self.get_run(run_id)
        if not run:
            return None
        return run.get("equity_curve")

    def get_trades(self, run_id: str) -> list[dict[str, Any]] | None:
        run = self.get_run(run_id)
        if not run:
            return None
        return run.get("trades")

    def get_liquidations(self, run_id: str) -> list[dict[str, Any]] | None:
        run = self.get_run(run_id)
        if not run:
            return None
        return run.get("liquidations")

    def get_parameters(self, run_id: str) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if not run:
            return None
        return run.get("parameters")


class FileTradingRunRepository(TradingRunRepository):
    """
    Reads versioned JSON runs from a manifest store.
    Optional test fixtures when include_fixtures=True or TRADING_RUN_INCLUDE_FIXTURES=1.
    """

    def __init__(self, root: Path, *, include_fixtures: bool | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if include_fixtures is None:
            include_fixtures = os.environ.get("TRADING_RUN_INCLUDE_FIXTURES", "0") == "1"
        self.include_fixtures = include_fixtures
        self._cache: dict[str, dict[str, Any]] = {}

    def _load_manifest(self) -> list[str]:
        manifest = self.root / "manifest.json"
        if not manifest.exists():
            ids = []
        else:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            ids = list(data.get("run_ids", []))
        if self.include_fixtures:
            for fid in ALL_FIXTURES:
                if fid not in ids:
                    ids.append(fid)
        return ids

    def _load_file(self, run_id: str) -> dict[str, Any] | None:
        if run_id in self._cache:
            return self._cache[run_id]
        if run_id in ALL_FIXTURES and self.include_fixtures:
            run = ALL_FIXTURES[run_id]()
            self._cache[run_id] = run
            return run
        path = self.root / f"{run_id}.json"
        if not path.exists():
            return None
        run = json.loads(path.read_text(encoding="utf-8"))
        validate_run_or_raise(run)
        self._cache[run_id] = run
        return run

    def list_runs(self) -> list[dict[str, Any]]:
        rows = []
        for run_id in self._load_manifest():
            run = self._load_file(run_id)
            if not run:
                continue
            strat = run.get("strategy") or {}
            exec_block = run.get("execution") or {}
            rows.append(
                {
                    "run_id": run_id,
                    "run_status": run.get("run_status"),
                    "created_at": run.get("created_at"),
                    "strategy_id": strat.get("strategy_id"),
                    "strategy_name": strat.get("strategy_name"),
                    "strategy_version": strat.get("strategy_version"),
                    "execution_realism_level": exec_block.get("execution_realism_level"),
                }
            )
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return rows

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._load_file(run_id)
