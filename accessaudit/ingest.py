"""ingest.py — Loads company assets data: HR roster + system access records.

Default source: local JSON files, so the whole tool runs with zero external
accounts or credentials — drop in exports from your real HR/IAM systems and
point the CLI/dashboard at that folder instead.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Employee, AccessRecord


def load_employees(path: str | Path) -> list[Employee]:
    data = json.loads(Path(path).read_text())
    return [Employee(**row) for row in data]


def load_access_records(path: str | Path) -> list[AccessRecord]:
    data = json.loads(Path(path).read_text())
    return [AccessRecord(**row) for row in data]
