from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from crypto_trading_bot.geometry_v2 import (GeometryPoint, ObjectiveType, PointSource,
    ProjectionDirection, RollingGeometryEngine, RollingObjectiveCalculatorV1)
from crypto_trading_bot.research_v2.resampling import ResampledCandle, resample_table

@dataclass(frozen=True, slots=True)
class ObjectiveEvent:
    objective: str
    first_reached_at: str
    first_reached_price: str
    bars_since_projection: int

@dataclass(frozen=True, slots=True)
class ReplayResult:
    symbol: str; timeframe: str; seed_id: str; projection_algorithm: str
    projection_algorithm_version: int; confirmation_rule: str; range_start: str; range_end: str
    generations: tuple[dict, ...]; candles: tuple[dict, ...]
    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

class LegacyTwoBarBenchmarkRunner:
    """Isolated V1 benchmark; never authoritative for V2 research."""
    confirmation_rule = "BENCHMARK_ONLY_FRESH_CROSS_THEN_2_BAR_REVERSAL_V2"
    def __init__(self): self.calculator = RollingObjectiveCalculatorV1()
    def run(self, candles: list[ResampledCandle], seed: dict, max_generations: int = 30) -> ReplayResult:
        points = tuple(_point(x) for x in seed["points"])
        engine = RollingGeometryEngine(self.calculator); active = engine.seed(points)
        records, events, bars, candidate_bar = [], {}, 0, -1
        previous = extreme_price = extreme_at = None
        replay = [c for c in candles if c.open_time_utc > points[-1].timestamp]
        for candle in replay:
            bars += 1; projection = active.projection
            for objective, level in ((ObjectiveType.COP, projection.cop_price), (ObjectiveType.OP, projection.op_price), (ObjectiveType.XOP, projection.xop_price)):
                if objective.value not in events and _crossed(previous, candle, projection.direction, level):
                    events[objective.value] = ObjectiveEvent(objective.value, candle.open_time_utc.isoformat(), str(level), bars)
            if projection.state.value == "PROJECTED" and events:
                first = next(x for x in (ObjectiveType.COP, ObjectiveType.OP, ObjectiveType.XOP) if x.value in events)
                active = engine.mark_candidate(first, candle.close_time_utc); candidate_bar = bars
                extreme_price, extreme_at = _extreme(candle, projection.direction)
            elif projection.state.value == "CANDIDATE":
                latest_price, latest_at = _extreme(candle, projection.direction)
                if _more_extreme(latest_price, extreme_price, projection.direction):
                    extreme_price, extreme_at = latest_price, latest_at
                    candidate_bar = bars
                leg = abs(active.window.b1.price - active.window.a1.price)
                reversal = max(extreme_price * Decimal("0.005"), leg * Decimal("0.20"))
                if bars >= candidate_bar + 2 and _reversed(candle, extreme_price, reversal, projection.direction):
                    old = active
                    new = engine.confirm_candidate(f"P{old.generation_id + 5}", extreme_at, extreme_price, candle.close_time_utc)
                    records.append(_record(old, new.generation_id, events, extreme_price, extreme_at, candle.close_time_utc))
                    active, events, bars, candidate_bar = new, {}, 0, -1; extreme_price = extreme_at = None
                    if len(records) >= max_generations: break
            previous = candle
        serialized = tuple(_candle(c) for c in replay)
        range_start = serialized[0]["open_time_utc"] if serialized else seed["points"][-1]["timestamp"]
        range_end = serialized[-1]["open_time_utc"] if serialized else seed["points"][-1]["timestamp"]
        return ReplayResult(seed["symbol"], seed["timeframe"], seed["seed_id"], self.calculator.algorithm,
            self.calculator.version, self.confirmation_rule, range_start, range_end, tuple(records), serialized)

def load_resampled_partitions(paths: list[Path], timeframe="4H"):
    return resample_table(pa.concat_tables([pq.read_table(p) for p in sorted(paths)]), timeframe)
def _point(x):
    at = datetime.fromisoformat(x["timestamp"]); return GeometryPoint(x["point_id"], at, Decimal(x["price"]), PointSource.MANUAL_SEED, at)
def _reached(c,d,l): return c.high >= l if d is ProjectionDirection.UP else c.low <= l
def _crossed(previous,c,d,l):
    if previous is None: return False
    return previous.high < l <= c.high if d is ProjectionDirection.UP else previous.low > l >= c.low
def _extreme(c,d): return (c.high,c.open_time_utc) if d is ProjectionDirection.UP else (c.low,c.open_time_utc)
def _more_extreme(value,current,d): return value > current if d is ProjectionDirection.UP else value < current
def _reversed(c,extreme,distance,d): return c.close <= extreme-distance if d is ProjectionDirection.UP else c.close >= extreme+distance
def _record(old,next_id,events,price,extreme_at,confirmed_at):
    p=old.projection
    return {"generation_id":old.generation_id,"created_at":old.created_at.isoformat(),"points":[{"point_id":x.point_id,"timestamp":x.timestamp.isoformat(),"price":str(x.price)} for x in old.window.points],"direction":p.direction.value,"cop_price":str(p.cop_price),"op_price":str(p.op_price),"xop_price":str(p.xop_price),"projection_algorithm":p.projection_algorithm,"projection_algorithm_version":p.projection_algorithm_version,"objective_events":{k:asdict(v) for k,v in events.items()},"candidate_objective":p.candidate_objective.value,"candidate_at":p.candidate_at.isoformat(),"confirmed_c":{"timestamp":extreme_at.isoformat(),"price":str(price)},"confirmed_at":confirmed_at.isoformat(),"next_generation_id":next_id}
def _candle(c):
    return {"open_time_utc":c.open_time_utc.isoformat(),"close_time_utc":c.close_time_utc.isoformat(),"open":str(c.open),"high":str(c.high),"low":str(c.low),"close":str(c.close),"volume":str(c.volume),"trade_count":c.trade_count}


# Compatibility import for forensic reproduction only. The command-line entry
# point refuses to run it unless the benchmark flag is explicitly supplied.
RollingReplayRunner = LegacyTwoBarBenchmarkRunner
