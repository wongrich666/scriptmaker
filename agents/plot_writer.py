# agents/plot_writer.py
from prompt_runtime import compose_prompt
from services.llm_client import call_agent


def _base_data(brief, character_bible, **kwargs):
    data = {
        "story_brief": brief,
        "character_bible": character_bible,
        "genre": brief.get("genre", ""),
        "style": brief.get("style", ""),
        "core_conflict": brief.get("core_conflict", ""),
        "banned_items": brief.get("banned_items", []),
        "reference_text": brief.get("reference_text", ""),
        "framework_text": brief.get("framework_text", ""),
    }
    data.update(kwargs)
    return data


def generate_plot_outline(brief, character_bible, llm_call, selected_model):
    data = _base_data(
        brief,
        character_bible,
        output_granularity="outline",
    )
    prompt = compose_prompt("outline", data, mode=brief.get("mode"))
    return call_agent(prompt, selected_model, "writer_b", llm_call=llm_call, temperature=0.7, max_tokens=4096)


def rewrite_plot_outline(brief, character_bible, previous_draft, review_json, llm_call, selected_model):
    data = _base_data(
        brief,
        character_bible,
        previous_draft=previous_draft,
        review_json=review_json,
        rewrite_instruction=review_json.get("rewrite_instruction", ""),
    )
    prompt = compose_prompt("outline_rewrite", data, mode=brief.get("mode"))
    return call_agent(prompt, selected_model, "writer_b", llm_call=llm_call, temperature=0.6, max_tokens=4096)


def generate_episode_plan(brief, character_bible, approved_outline, llm_call, selected_model):
    data = _base_data(
        brief,
        character_bible,
        approved_outline=approved_outline,
        output_granularity="episode_plan",
    )
    prompt = compose_prompt("episode_plan", data, mode=brief.get("mode"))
    return call_agent(
        prompt,
        selected_model,
        "writer_b",
        llm_call=llm_call,
        temperature=0.7,
        max_tokens=4096,
    )


def rewrite_episode_plan(brief, character_bible, approved_outline, previous_draft, review_json, llm_call, selected_model):
    data = _base_data(
        brief,
        character_bible,
        approved_outline=approved_outline,
        previous_draft=previous_draft,
        review_json=review_json,
        rewrite_instruction=review_json.get("rewrite_instruction", ""),
    )
    prompt = compose_prompt("episode_plan_rewrite", data, mode=brief.get("mode"))
    return call_agent(prompt, selected_model, "writer_b", llm_call=llm_call, temperature=0.6, max_tokens=4096)


def generate_episode_script(
    brief,
    character_bible,
    approved_plan,
    episode_no,
    current_episode_plan,
    previous_episode_summary,
    llm_call,
    selected_model,
):
    data = _base_data(
        brief,
        character_bible,
        approved_plan=approved_plan,
        current_episode_no=episode_no,
        current_episode_plan=current_episode_plan,
        previous_episode_summary=previous_episode_summary or "",
        output_granularity="single_episode_script",
    )
    prompt = compose_prompt("single_episode_script", data, mode=brief.get("mode"))
    return call_agent(prompt, selected_model, "writer_b", llm_call=llm_call, temperature=0.75, max_tokens=8192)


def rewrite_episode_script(
    brief,
    character_bible,
    approved_plan,
    episode_no,
    current_episode_plan,
    previous_episode_summary,
    previous_draft,
    review_json,
    llm_call,
    selected_model,
):
    data = _base_data(
        brief,
        character_bible,
        approved_plan=approved_plan,
        current_episode_no=episode_no,
        current_episode_plan=current_episode_plan,
        previous_episode_summary=previous_episode_summary or "",
        previous_draft=previous_draft,
        review_json=review_json,
        rewrite_instruction=review_json.get("rewrite_instruction", ""),
    )
    prompt = compose_prompt("single_episode_rewrite", data, mode=brief.get("mode"))
    return call_agent(prompt, selected_model, "writer_b", llm_call=llm_call, temperature=0.65, max_tokens=8192)