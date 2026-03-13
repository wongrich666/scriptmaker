# agents/character_writer.py
import json
from prompt_runtime import compose_prompt
from services.llm_client import call_agent


def _build_character_data(brief: dict, previous_draft=None, review_json=None):
    data = {
        "story_brief": brief,
        "genre": brief.get("genre", ""),
        "style": brief.get("style", ""),
        "core_conflict": brief.get("core_conflict", ""),
        "banned_items": brief.get("banned_items", []),
        "reference_text": brief.get("reference_text", ""),
        "framework_text": brief.get("framework_text", ""),
    }
    if previous_draft is not None:
        data["previous_draft"] = previous_draft
    if review_json is not None:
        data["review_json"] = review_json
        data["rewrite_instruction"] = review_json.get("rewrite_instruction", "")
    return data


def generate_character_bible(brief, llm_call, selected_model):
    data = _build_character_data(brief)
    prompt = compose_prompt("character_bible", data, mode=brief.get("mode"))
    return call_agent(
        prompt,
        selected_model,
        "writer_a",
        llm_call=llm_call,
        temperature=0.7,
        max_tokens=4096,
    )


def rewrite_character_bible(brief, previous_draft, review_json, llm_call, selected_model):
    data = _build_character_data(brief, previous_draft=previous_draft, review_json=review_json)
    prompt = compose_prompt("character_rewrite", data, mode=brief.get("mode"))
    return call_agent(
        prompt,
        selected_model,
        "writer_a",
        llm_call=llm_call,
        temperature=0.6,
        max_tokens=4096,
    )