"""Explicit model decisions for hermetic HTTP tests; never production routing."""
from __future__ import annotations

import json


PLANNER_PROMPT_PREFIX = "你是捷境 AI CEO 的语义任务规划器"


def semantic_decision(*, intent: str, **changes) -> dict:
    """Build the complete wire schema from a test's declared intent."""
    return {
        "status": "ready", "intent": intent, "project_action": "none",
        "product_name": "", "question": "", "search": "none", "query": "",
        "source_mode": "unknown", "read_images": False, "save_artifact": False,
        "candidate_count": 1, "excluded_candidates": [], "listing_deferred": False,
        "steps": ["回答商家问题"], "research_delivery": "none", "research_queries": [],
        "product_fact_proposals": [],
        **changes,
    }


def semantic_decision_json(*, intent: str, **changes) -> str:
    return json.dumps(semantic_decision(intent=intent, **changes), ensure_ascii=False)
