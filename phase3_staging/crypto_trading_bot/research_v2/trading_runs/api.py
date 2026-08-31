"""REST API for trading run results."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify

from .reconciliation import reconcile_run
from .repository import TradingRunRepository

bp = Blueprint("trading_runs_api", __name__, url_prefix="/api/trading-runs")
_repo: TradingRunRepository | None = None


def init_repository(repo: TradingRunRepository) -> None:
    global _repo
    _repo = repo


def _repo_or_404():
    if _repo is None:
        return None, (jsonify({"error": "repository not initialized"}), 503)
    return _repo, None


@bp.route("", methods=["GET"])
def list_runs():
    repo, err = _repo_or_404()
    if err:
        return err
    return jsonify({"runs": repo.list_runs()})


@bp.route("/<run_id>", methods=["GET"])
def get_run(run_id: str):
    repo, err = _repo_or_404()
    if err:
        return err
    run = repo.get_run(run_id)
    if not run:
        return jsonify({"error": "not found"}), 404
    out = dict(run)
    out["reconciliation"] = reconcile_run(run)
    return jsonify(out)


@bp.route("/<run_id>/summary", methods=["GET"])
def get_summary(run_id: str):
    repo, err = _repo_or_404()
    if err:
        return err
    summary = repo.get_summary(run_id)
    if not summary:
        return jsonify({"error": "not found"}), 404
    run = repo.get_run(run_id)
    summary["reconciliation"] = reconcile_run(run) if run else None
    return jsonify(summary)


@bp.route("/<run_id>/equity", methods=["GET"])
def get_equity(run_id: str):
    repo, err = _repo_or_404()
    if err:
        return err
    curve = repo.get_equity_curve(run_id)
    if curve is None:
        run = repo.get_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        return jsonify({"equity_curve": None, "status": "NOT_AVAILABLE"})
    return jsonify({"equity_curve": curve})


@bp.route("/<run_id>/trades", methods=["GET"])
def get_trades(run_id: str):
    repo, err = _repo_or_404()
    if err:
        return err
    trades = repo.get_trades(run_id)
    if trades is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"trades": trades})


@bp.route("/<run_id>/liquidations", methods=["GET"])
def get_liquidations(run_id: str):
    repo, err = _repo_or_404()
    if err:
        return err
    liq = repo.get_liquidations(run_id)
    if liq is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"liquidations": liq})


@bp.route("/<run_id>/parameters", methods=["GET"])
def get_parameters(run_id: str):
    repo, err = _repo_or_404()
    if err:
        return err
    params = repo.get_parameters(run_id)
    if params is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"parameters": params})


def register_trading_run_api(server, repo: TradingRunRepository) -> None:
    init_repository(repo)
    server.register_blueprint(bp)
