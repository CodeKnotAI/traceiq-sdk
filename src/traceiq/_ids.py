"""Stable id helpers for workflow_id derivation."""

from __future__ import annotations

import hashlib


def stable_workflow_id(name: str) -> str:
    """Deterministic workflow_id from a human name: sha1(name)[:16]."""
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
