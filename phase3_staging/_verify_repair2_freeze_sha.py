#!/usr/bin/env python3
"""Verify frozen composite artifact SHA256 against freeze manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ART = Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1")


def main() -> int:
    freeze = json.loads((ART / "composite_spec_freeze_manifest_v1.json").read_text(encoding="utf-8"))
    expected = freeze["SHA256"]
    out = {}
    ok = True
    for name, exp in expected.items():
        got = hashlib.sha256((ART / name).read_bytes()).hexdigest()
        match = got == exp
        out[name] = {"expected": exp, "got": got, "match": match}
        ok = ok and match
        print(f"{name}: {'PASS' if match else 'FAIL'}")
    summary = {
        "COMPOSITE_SEARCH_SPEC_SHA_MATCH": "PASS" if out["composite_search_spec_v1.json"]["match"] else "FAIL",
        "COMPOSITE_TEMPLATES_SHA_MATCH": "PASS" if out["composite_templates_v1.json"]["match"] else "FAIL",
        "COMPOSITE_ATOMIC_BANK_SHA_MATCH": "PASS" if out["composite_atomic_bank_v1.json"]["match"] else "FAIL",
        "DEVELOPMENT_CORPUS_SHA_MATCH": "PASS" if out["development_corpus_manifest_v1.json"]["match"] else "FAIL",
        "details": out,
        "OOS_OPENED": freeze.get("OOS_OPENED", "NO"),
    }
    (ART / "repair2_freeze_sha_check_v1.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "details"}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
