"""Role and permission contract for Jiejing SaaS tenants."""

from __future__ import annotations

from typing import Any


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": {
        "manage_team",
        "manage_store",
        "manage_connections",
        "create_task",
        "view_report",
        "approve_high_risk",
        "execute_confirmed_action",
        "view_audit",
        "manage_billing",
    },
    "admin": {
        "manage_store",
        "manage_connections",
        "create_task",
        "view_report",
        "approve_high_risk",
        "execute_confirmed_action",
        "view_audit",
    },
    "operator": {
        "create_task",
        "view_report",
        "execute_confirmed_action",
    },
    "media": {
        "create_task",
        "view_report",
    },
    "support": {
        "create_task",
        "view_report",
    },
    "finance": {
        "view_report",
        "view_audit",
        "manage_billing",
    },
    "viewer": {
        "view_report",
    },
}


def valid_role(role: str) -> bool:
    return role in ROLE_PERMISSIONS


def permissions_for_role(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, set()))


def role_summary() -> list[dict[str, Any]]:
    labels = {
        "owner": "Owner",
        "admin": "Admin",
        "operator": "Operator",
        "media": "Media",
        "support": "Support",
        "finance": "Finance",
        "viewer": "Viewer",
    }
    return [
        {
            "role": role,
            "label": labels.get(role, role),
            "permissions": permissions_for_role(role),
        }
        for role in ROLE_PERMISSIONS
    ]


def has_permission(role: str | None, permission: str) -> bool:
    if not role:
        return False
    return permission in ROLE_PERMISSIONS.get(role, set())
