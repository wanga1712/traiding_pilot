from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


QWEN_ACTIONS = (
    "OPEN_LONG",
    "OPEN_SHORT",
    "HOLD",
    "OPEN_HEDGE",
    "CLOSE_HEDGE",
    "AVERAGE_PRIMARY",
    "REDUCE_POSITION",
    "EXIT",
    "SKIP",
)
QWEN_DIRECTIONS = ("LONG", "SHORT", "NONE")
QWEN_REQUIRED_KEYS = {
    "action",
    "direction",
    "confidence",
    "reason",
    "risk_assessment",
}
FORBIDDEN_FEATURE_PREFIXES = (
    "fwd_",
    "mfe_",
    "max_future_",
    "min_future_",
    "time_to_",
    "censor_",
    "target_",
    "best_action",
    "utility_",
    "long_favorable",
    "short_favorable",
    "long_liquidation",
    "short_liquidation",
    "long_risk_limit",
    "short_risk_limit",
    "long_recovered",
    "short_recovered",
)

QWEN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(QWEN_ACTIONS)},
        "direction": {"type": "string", "enum": list(QWEN_DIRECTIONS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 100},
        "reason": {"type": "string"},
        "risk_assessment": {"type": "string"},
    },
    "required": sorted(QWEN_REQUIRED_KEYS),
    "additionalProperties": False,
}


class QwenContractError(ValueError):
    pass


@dataclass(frozen=True)
class QwenConfig:
    model_id: str = "qwen2.5:7b"
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 120.0
    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 4096
    num_predict: int = 96
    keep_alive: str = "30m"
    max_attempts: int = 2


@dataclass(frozen=True)
class QwenDecision:
    action: str
    direction: str
    confidence: float
    reason: str
    risk_assessment: str
    valid: bool
    fallback_used: bool
    validation_error: str | None
    latency_seconds: float
    request_hash: str
    model_id: str
    model_digest: str | None
    cached: bool = False


HttpCall = Callable[[str, str, dict[str, Any] | None, float], dict[str, Any]]


def _default_http_call(
    url: str,
    method: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _assert_causal(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized.startswith(FORBIDDEN_FEATURE_PREFIXES):
                raise QwenContractError(f"forbidden future field at {path}.{key}")
            _assert_causal(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_causal(item, path=f"{path}[{index}]")
    elif isinstance(value, (float, int)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise QwenContractError(f"non-finite value at {path}")


def _direction_for_action(action: str) -> str:
    if action == "OPEN_LONG":
        return "LONG"
    if action == "OPEN_SHORT":
        return "SHORT"
    return "NONE"


def validate_qwen_response(value: Any) -> tuple[str, str, float, str, str]:
    if not isinstance(value, dict):
        raise QwenContractError("response is not an object")
    if set(value) != QWEN_REQUIRED_KEYS:
        raise QwenContractError(
            f"response keys must be exactly {sorted(QWEN_REQUIRED_KEYS)}"
        )
    action = value["action"]
    direction = value["direction"]
    confidence = value["confidence"]
    reason = value["reason"]
    risk_assessment = value["risk_assessment"]
    if action not in QWEN_ACTIONS:
        raise QwenContractError(f"unknown action: {action!r}")
    if direction not in QWEN_DIRECTIONS:
        raise QwenContractError(f"unknown direction: {direction!r}")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise QwenContractError("confidence must be numeric")
    confidence_value = float(confidence)
    if not math.isfinite(confidence_value):
        raise QwenContractError("confidence is not finite")
    if confidence_value > 1.0:
        confidence_value /= 100.0
    if confidence_value < 0.0 or confidence_value > 1.0:
        raise QwenContractError("confidence outside 0..1 after normalization")
    expected_direction = _direction_for_action(action)
    if expected_direction != "NONE" and direction != expected_direction:
        raise QwenContractError(
            f"direction {direction!r} inconsistent with action {action!r}"
        )
    for field, text in (("reason", reason), ("risk_assessment", risk_assessment)):
        if not isinstance(text, str) or not text.strip():
            raise QwenContractError(f"{field} must be a non-empty string")
        if len(text) > 1000:
            raise QwenContractError(f"{field} exceeds 1000 characters")
    return action, direction, confidence_value, reason.strip(), risk_assessment.strip()


class QwenPolicyAdapter:
    def __init__(
        self,
        *,
        config: QwenConfig,
        log_path: Path,
        http_call: HttpCall | None = None,
    ) -> None:
        self.config = config
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.http_call = http_call or _default_http_call
        self._identity: dict[str, Any] | None = None
        self._cache = self._load_cache()

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        cache: dict[str, dict[str, Any]] = {}
        if not self.log_path.exists():
            return cache
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = record.get("request_id")
            decision = record.get("decision")
            identity = record.get("model_identity")
            if request_id and isinstance(decision, dict) and identity:
                cache[request_id] = record
        return cache

    def runtime_identity(self) -> dict[str, Any]:
        if self._identity is not None:
            return self._identity
        tags = self.http_call(
            f"{self.config.base_url}/api/tags",
            "GET",
            None,
            self.config.timeout_seconds,
        )
        selected = next(
            (item for item in tags.get("models", []) if item.get("name") == self.config.model_id),
            None,
        )
        if selected is None:
            raise QwenContractError(f"model not installed: {self.config.model_id}")
        try:
            running = self.http_call(
                f"{self.config.base_url}/api/ps",
                "GET",
                None,
                self.config.timeout_seconds,
            )
        except Exception:
            running = {"models": []}
        loaded = next(
            (item for item in running.get("models", []) if item.get("name") == self.config.model_id),
            None,
        )
        self._identity = {
            "runtime": "OLLAMA_LOCAL_HTTP",
            "model_id": self.config.model_id,
            "digest": selected.get("digest"),
            "size_bytes": selected.get("size"),
            "details": selected.get("details", {}),
            "loaded": loaded is not None,
            "loaded_details": loaded or {},
        }
        return self._identity

    def _prompt(self, request: dict[str, Any]) -> tuple[str, str]:
        system = (
            "You are a constrained trading-policy validator. Use only the supplied "
            "causal facts. Do not infer or invent future prices, targets, fills, or "
            "portfolio state. Return exactly one JSON object matching the schema. "
            "Choose only an action listed in allowed_actions. "
            "confidence is an integer from 0 to 100. Keep reason and "
            "risk_assessment to at most 12 words each."
        )
        prompt = (
            "Validate the next action. Risk Engine remains authoritative and may "
            "reject any action.\nCAUSAL_REQUEST="
            + json.dumps(request, sort_keys=True, separators=(",", ":"))
        )
        return system, prompt

    def _append_log(self, record: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def decide(
        self,
        *,
        decision_at: str,
        market_features: dict[str, Any],
        catboost: dict[str, Any],
        portfolio_state: dict[str, Any],
        risk: dict[str, Any],
        fallback_action: str,
        market_events: list[dict[str, Any]] | None = None,
        allowed_actions: list[str] | None = None,
    ) -> QwenDecision:
        identity = self.runtime_identity()
        normalized_allowed = (
            list(QWEN_ACTIONS)
            if allowed_actions is None
            else list(dict.fromkeys(str(action) for action in allowed_actions))
        )
        invalid_actions = sorted(set(normalized_allowed) - set(QWEN_ACTIONS))
        if invalid_actions:
            raise QwenContractError(
                f"unknown allowed actions: {invalid_actions}"
            )
        request = {
            "decision_at": str(decision_at),
            "market_features": market_features,
            "catboost": catboost,
            "portfolio_state": portfolio_state,
            "risk": risk,
            "fallback_action": fallback_action,
            "market_events": market_events or [],
            "allowed_actions": normalized_allowed,
        }
        _assert_causal(request)
        request_hash = _sha256_json(request)
        cached_record = self._cache.get(request_hash)
        if cached_record is not None:
            cached_identity = cached_record.get("model_identity", {})
            if (
                cached_identity.get("model_id") == identity.get("model_id")
                and cached_identity.get("digest") == identity.get("digest")
            ):
                cached_decision = dict(cached_record["decision"])
                if cached_decision.get("action") in normalized_allowed:
                    cached_decision["latency_seconds"] = 0.0
                    cached_decision["cached"] = True
                    decision = QwenDecision(**cached_decision)
                    self._append_log(
                        {
                            "request_id": request_hash,
                            "decision_at": decision_at,
                            "model_identity": identity,
                            "request": request,
                            "cache_replay": True,
                            "decision": asdict(decision),
                        }
                    )
                    return decision
        system, prompt = self._prompt(request)
        raw_responses: list[str] = []
        errors: list[str] = []
        started = time.perf_counter()
        parsed: tuple[str, str, float, str, str] | None = None
        body: dict[str, Any] = {}
        for _ in range(max(1, self.config.max_attempts)):
            payload = {
                "model": self.config.model_id,
                "system": system,
                "prompt": prompt,
                "stream": False,
                "format": QWEN_RESPONSE_SCHEMA,
                "keep_alive": self.config.keep_alive,
                "options": {
                    "temperature": self.config.temperature,
                    "seed": self.config.seed,
                    "num_ctx": self.config.num_ctx,
                    "num_predict": self.config.num_predict,
                },
            }
            body = self.http_call(
                f"{self.config.base_url}/api/generate",
                "POST",
                payload,
                self.config.timeout_seconds,
            )
            raw = body.get("response", "")
            raw_responses.append(raw)
            try:
                candidate = validate_qwen_response(json.loads(raw))
                if candidate[0] not in normalized_allowed:
                    raise QwenContractError(
                        f"action {candidate[0]!r} is not allowed in current state"
                    )
                parsed = candidate
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        latency = time.perf_counter() - started
        if parsed is None:
            decision = QwenDecision(
                action=fallback_action,
                direction=_direction_for_action(fallback_action),
                confidence=0.0,
                reason="Qwen response rejected; safe fallback to CatBoost action.",
                risk_assessment="Qwen response failed independent contract validation.",
                valid=False,
                fallback_used=True,
                validation_error="; ".join(errors),
                latency_seconds=latency,
                request_hash=request_hash,
                model_id=self.config.model_id,
                model_digest=identity.get("digest"),
            )
        else:
            action, direction, confidence, reason, risk_assessment = parsed
            decision = QwenDecision(
                action=action,
                direction=direction,
                confidence=confidence,
                reason=reason,
                risk_assessment=risk_assessment,
                valid=True,
                fallback_used=False,
                validation_error=None,
                latency_seconds=latency,
                request_hash=request_hash,
                model_id=self.config.model_id,
                model_digest=identity.get("digest"),
            )
        self._append_log(
            {
                "request_id": request_hash,
                "decision_at": decision_at,
                "model_identity": identity,
                "request": request,
                "raw_responses": raw_responses,
                "server_response": {
                    "done_reason": body.get("done_reason"),
                    "eval_count": body.get("eval_count"),
                    "total_duration": body.get("total_duration"),
                },
                "decision": asdict(decision),
                "validation_errors": errors,
            }
        )
        self._cache[request_hash] = {
            "request_id": request_hash,
            "model_identity": identity,
            "decision": asdict(decision),
        }
        return decision


def run_contract_preflight(
    *,
    output_root: Path,
    config: QwenConfig = QwenConfig(),
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / "qwen_contract_test_v1.jsonl"
    log_path.unlink(missing_ok=True)
    adapter = QwenPolicyAdapter(config=config, log_path=log_path)
    identity = adapter.runtime_identity()
    fixture = {
        "decision_at": "2020-07-15T12:59:59Z",
        "market_features": {
            "atr14": 2.4,
            "rsi14": 55.0,
            "macd_histogram": 0.12,
            "stoch_k": 62.0,
            "stoch_d": 58.0,
            "adx14": 27.0,
        },
        "catboost": {
            "long_probability": 0.61,
            "short_probability": 0.18,
            "skip_probability": 0.21,
            "predicted_downside_24h": -0.031,
            "predicted_upside_24h": 0.047,
        },
        "portfolio_state": {
            "state": "FLAT",
            "free_margin_fraction": 0.40,
            "net_exposure_fraction": 0.0,
        },
        "risk": {
            "risk_limit_fraction": 0.05,
            "remaining_thesis_risk_fraction": 0.05,
        },
    }
    decisions = []
    for _ in range(3):
        decisions.append(
            adapter.decide(
                decision_at=fixture["decision_at"],
                market_features=fixture["market_features"],
                catboost=fixture["catboost"],
                portfolio_state=fixture["portfolio_state"],
                risk=fixture["risk"],
                fallback_action="SKIP",
            )
        )
    normalized = [
        {
            "action": decision.action,
            "direction": decision.direction,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "risk_assessment": decision.risk_assessment,
        }
        for decision in decisions
    ]
    action_sequence = [(decision.action, decision.direction) for decision in decisions]
    confidence_sequence = [round(decision.confidence, 8) for decision in decisions]
    full_text_deterministic = len({json.dumps(x, sort_keys=True) for x in normalized}) == 1
    result = {
        "status": (
            "PASS"
            if all(decision.valid for decision in decisions)
            and len(set(action_sequence)) == 1
            else "FAIL"
        ),
        "model_identity": identity,
        "requests": len(decisions),
        "action_deterministic": len(set(action_sequence)) == 1,
        "confidence_deterministic": len(set(confidence_sequence)) == 1,
        "full_text_deterministic": full_text_deterministic,
        "all_valid": all(decision.valid for decision in decisions),
        "latency_seconds": [decision.latency_seconds for decision in decisions],
        "median_latency_seconds": float(
            __import__("statistics").median(
                [decision.latency_seconds for decision in decisions]
            )
        ),
        "decisions": normalized,
        "request_log": str(log_path),
    }
    (output_root / "qwen_contract_preflight_v1.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_contract_preflight(output_root=args.output_root), indent=2))
