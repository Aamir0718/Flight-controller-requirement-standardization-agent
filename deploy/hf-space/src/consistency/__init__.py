"""Consistency analysis module for detecting duplicate, similar, and contradictory requirements."""

from __future__ import annotations

from consistency.analyzer import ConsistencyAnalyzer, ConsistencyResult, RequirementRelationship

__all__ = [
    "ConsistencyAnalyzer",
    "ConsistencyResult",
    "RequirementRelationship",
]
