from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from crypto_trading_bot.research_v2.gpu_ai_policy.qwen_adapter import (
    QwenConfig,
    QwenContractError,
    QwenPolicyAdapter,
    validate_qwen_response,
)


class FakeOllama:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.generate_calls = 0

    def __call__(self, url: str, method: str, payload: dict | None, timeout: float) -> dict:
        if url.endswith("/api/tags"):
            return {
                "models": [
                    {
                        "name": "qwen2.5:7b",
                        "digest": "digest-v1",
                        "size": 123,
                        "details": {"parameter_size": "7.6B"},
                    }
                ]
            }
        if url.endswith("/api/ps"):
            return {
                "models": [
                    {
                        "name": "qwen2.5:7b",
                        "size_vram": 4741,
                    }
                ]
            }
        if url.endswith("/api/generate"):
            self.generate_calls += 1
            return {
                "response": json.dumps(self.response),
                "done_reason": "stop",
                "eval_count": 10,
                "total_duration": 100,
            }
        raise AssertionError(url)


@contextmanager
def _adapter_context(response: dict):
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
        root = Path(temporary)
        adapter = QwenPolicyAdapter(
            config=QwenConfig(model_id="qwen2.5:7b", max_attempts=2),
            log_path=root / "qwen.jsonl",
            http_call=FakeOllama(response),
        )
        yield adapter, root


def test_confidence_percentage_is_normalized_and_logged() -> None:
    with _adapter_context(
        {
            "action": "HOLD",
            "direction": "NONE",
            "confidence": 61,
            "reason": "Risk exceeds the available edge.",
            "risk_assessment": "Keep risk below the frozen limit.",
        }
    ) as (adapter, root):
        decision = adapter.decide(
            decision_at="2020-01-01T00:00:00Z",
            market_features={"rsi14": 50.0},
            catboost={"long_probability": 0.6, "short_probability": 0.2},
            portfolio_state={"state": "FLAT"},
            risk={"risk_limit_fraction": 0.05},
            fallback_action="SKIP",
        )
        assert decision.valid
        assert decision.action == "HOLD"
        assert 0.0 <= decision.confidence <= 1.0
        assert decision.confidence == pytest.approx(0.61)
        record = json.loads((root / "qwen.jsonl").read_text().splitlines()[0])
        assert record["model_identity"]["digest"] == "digest-v1"
        assert record["decision"]["valid"]


def test_invalid_response_falls_back_safely() -> None:
    with _adapter_context(
        {
            "action": "OPEN_LONG",
            "direction": "SHORT",
            "confidence": 0.9,
            "reason": "bad direction",
            "risk_assessment": "bad",
        }
    ) as (adapter, _):
        decision = adapter.decide(
            decision_at="2020-01-01T00:00:00Z",
            market_features={"rsi14": 50.0},
            catboost={"long_probability": 0.6},
            portfolio_state={"state": "FLAT"},
            risk={"risk_limit_fraction": 0.05},
            fallback_action="SKIP",
        )
        assert not decision.valid
        assert decision.fallback_used
        assert decision.action == "SKIP"
        assert decision.validation_error


def test_future_target_fields_are_rejected_before_inference() -> None:
    with _adapter_context(
        {
            "action": "SKIP",
            "direction": "NONE",
            "confidence": 0.5,
            "reason": "skip",
            "risk_assessment": "none",
        }
    ) as (adapter, _):
        with pytest.raises(QwenContractError):
            adapter.decide(
                decision_at="2020-01-01T00:00:00Z",
                market_features={"fwd_return_24h": 0.1},
                catboost={"long_probability": 0.6},
                portfolio_state={"state": "FLAT"},
                risk={"risk_limit_fraction": 0.05},
                fallback_action="SKIP",
            )


def test_exact_response_keys_are_enforced() -> None:
    with pytest.raises(QwenContractError, match="exactly"):
        validate_qwen_response(
            {
                "action": "HOLD",
                "direction": "NONE",
                "confidence": 0.5,
                "reason": "hold",
                "risk_assessment": "ok",
                "future_price": 100,
            }
        )


def test_request_hash_cache_replays_without_inference() -> None:
    response = {
        "action": "SKIP",
        "direction": "NONE",
        "confidence": 70,
        "reason": "No entry.",
        "risk_assessment": "Risk remains below the limit.",
    }
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
        root = Path(temporary)
        log_path = root / "qwen.jsonl"
        first_client = FakeOllama(response)
        first = QwenPolicyAdapter(
            config=QwenConfig(model_id="qwen2.5:7b"),
            log_path=log_path,
            http_call=first_client,
        )
        kwargs = {
            "decision_at": "2020-01-01T00:00:00Z",
            "market_features": {"rsi14": 50.0},
            "catboost": {"long_probability": 0.6},
            "portfolio_state": {"state": "FLAT"},
            "risk": {"risk_limit_fraction": 0.05},
            "fallback_action": "SKIP",
        }
        first.decide(**kwargs)
        second_client = FakeOllama(response)
        second = QwenPolicyAdapter(
            config=QwenConfig(model_id="qwen2.5:7b"),
            log_path=log_path,
            http_call=second_client,
        )
        replay = second.decide(**kwargs)
        assert replay.cached
        assert replay.latency_seconds == 0
        assert second_client.generate_calls == 0


def test_qwen_action_outside_current_state_falls_back_safely() -> None:
    with _adapter_context(
        {
            "action": "CLOSE_HEDGE",
            "direction": "NONE",
            "confidence": 90,
            "reason": "Close a hedge.",
            "risk_assessment": "No hedge exists.",
        }
    ) as (adapter, root):
        decision = adapter.decide(
            decision_at="2020-01-01T00:00:00Z",
            market_features={"rsi14": 50.0},
            catboost={"management_probabilities": {"OPEN_HEDGE": 0.2}},
            portfolio_state={
                "position_state": "PRIMARY_OPEN",
                "hedge_open": False,
            },
            risk={"risk_limit_fraction": 0.05},
            fallback_action="HOLD",
            allowed_actions=[
                "HOLD",
                "OPEN_HEDGE",
                "AVERAGE_PRIMARY",
                "REDUCE_POSITION",
                "EXIT",
            ],
        )
        assert not decision.valid
        assert decision.fallback_used
        assert decision.action == "HOLD"
        assert "not allowed" in (decision.validation_error or "")
        record = json.loads((root / "qwen.jsonl").read_text().splitlines()[-1])
        assert record["request"]["allowed_actions"] == [
            "HOLD",
            "OPEN_HEDGE",
            "AVERAGE_PRIMARY",
            "REDUCE_POSITION",
            "EXIT",
        ]
