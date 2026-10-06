"""Explicit external semantic-review success fixture; never used by production."""
import json


def supported_review(prompt):
    return {"contract_version": "listing_claim_review_v1", "reviews": [
        {"field": field, "text": text, "verdict": "supported", "evidence_keys": [next(iter(prompt["confirmed_facts"]))]}
        for field, text in prompt["buyer_copy"].items()]}


def review_response(kwargs, *, usage):
    try:
        prompt = json.loads(kwargs.get("user_prompt", "{}"))
    except (ValueError, TypeError):
        return None
    if prompt.get("contract") != "listing_claim_review_v1":
        return None
    return {"text": json.dumps(supported_review(prompt)), "_usage": usage}
