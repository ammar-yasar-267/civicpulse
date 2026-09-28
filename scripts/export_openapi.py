#!/usr/bin/env python3
"""Export the backend's OpenAPI schema to backend/openapi.json.

This is the seam between the two halves of the repo (§2.1): the frontend's types are
generated from this file by `npm run api:types`, so a backend field rename becomes a frontend
type error instead of a runtime surprise.

CI re-runs this and `npm run api:types`, then fails if either output differs from what is
committed — which is what "checked against the backend's OpenAPI schema" means in practice.
Run it after changing any route or schema:

    python scripts/export_openapi.py
    cd frontend && npm run api:types
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

OUTPUT = ROOT / "backend" / "openapi.json"


def main() -> int:
    from app.main import create_app

    schema = create_app().openapi()

    # sort_keys so the file is diff-stable: without it, dict ordering changes produce noisy
    # diffs and the CI drift check becomes useless.
    OUTPUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(schema['paths'])} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
