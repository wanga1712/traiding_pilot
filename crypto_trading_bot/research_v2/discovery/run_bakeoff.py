import argparse
import json
from pathlib import Path

from .bakeoff import run_formula_bakeoff


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--annotation-id", required=True)
    parser.add_argument("--warmup", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(run_formula_bakeoff(args.input, args.output, args.annotation_id, warmup=args.warmup), indent=2))


if __name__ == "__main__":
    main()
