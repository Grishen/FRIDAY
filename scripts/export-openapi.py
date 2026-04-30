#!/usr/bin/env python3
"""Write FastAPI OpenAPI schema to docs/api/openapi.json (no running server).

Usage (from repo root):
  PYTHONPATH=services/api/src python scripts/export-openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "services" / "api" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> None:
    from friday_api.main import create_app

    app = create_app()
    schema = app.openapi()
    out = ROOT / "docs" / "api" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
