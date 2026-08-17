"""Dump the FastAPI app's OpenAPI schema to stdout (BLUEPRINT.md §4.3, §8 step 8).

The one piece `frontend/scripts/generate-contract.ts`'s `make contract` shells
out to: import `main.app` and call `app.openapi()` -- this needs no live
Postgres/Redis (nothing in `main.py`'s module-level code touches the network;
the DB/Redis/checkpointer connections open inside the `lifespan` context
manager, which a plain import never enters, BLUEPRINT.md §8's own note on
this). Run from `backend/` with `src` on the import path, matching every
other entrypoint in this repo (`main.py`'s own docstring):

    uv run python scripts/dump_openapi.py > /tmp/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from main import app


def main() -> None:
    json.dump(app.openapi(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
