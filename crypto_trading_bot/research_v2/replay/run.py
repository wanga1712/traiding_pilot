import argparse, json
from pathlib import Path
from .runner import RollingReplayRunner, load_resampled_partitions
def main():
    p=argparse.ArgumentParser(); p.add_argument("--market-root",type=Path,required=True); p.add_argument("--seed",type=Path,required=True); p.add_argument("--start-year",type=int,required=True); p.add_argument("--end-year",type=int,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--max-generations",type=int,default=30); p.add_argument("--allow-legacy-benchmark",action="store_true"); a=p.parse_args()
    if not a.allow_legacy_benchmark:
        p.error("automatic replay is disabled at the V2 visual gate; use the manual confirmation UI")
    paths=[x for y in range(a.start_year,a.end_year+1) for x in (a.market_root/str(y)).glob("*.parquet")]
    result=RollingReplayRunner().run(load_resampled_partitions(paths),json.loads(a.seed.read_text()),a.max_generations); result.write_json(a.output)
    counts={x:sum(x in g["objective_events"] for g in result.generations) for x in ("COP","OP","XOP")}; print(f"GENERATIONS={len(result.generations)} COP={counts['COP']} OP={counts['OP']} XOP={counts['XOP']}")
if __name__ == "__main__": main()
