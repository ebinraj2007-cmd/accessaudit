"""models.py — Core data structures."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional


@dataclass
class Employee:
    id: str
    name: str
    email: str
    department: str
    role: str
    status: str              # "active" | "terminated"
    termination_date: Optional[str] = None   # ISO date string, only if terminated


@dataclass
class AccessRecord:
    id: str
    user_email: str
    system: str               # e.g. "AWS Console", "Payroll System", "VPN"
    access_level: str         # e.g. "admin", "standard", "read-only"
    granted_date: str
    last_used_date: Optional[str] = None      # None = never used / no login telemetry


@dataclass
class Finding:
    id: str
    employee_email: str
    employee_name: str
    system: str
    access_level: str
    issue_type: str            # "orphaned_access" | "dormant_access" | "excessive_privilege"
    severity: int               # 1 (low) - 5 (critical)
    reasoning: str
    engine: str                 # "rules" | "llm"
    status: str = "open"         # "open" | "revoked" | "password_reset" | "dismissed"

    def to_dict(self):
        return asdict(self)
