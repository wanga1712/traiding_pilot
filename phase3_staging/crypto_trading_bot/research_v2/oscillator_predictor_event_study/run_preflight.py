"""S13 canonical preflight for OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1."""
from __future__ import annotations

import json
import sys

from .s13_canonical_preflight import run_s13_canonical_preflight


def main() -> dict:
    run_study = "--run-study" in sys.argv
    result = run_s13_canonical_preflight(run_study_after=run_study)
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    main()
