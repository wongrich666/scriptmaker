# agents/reviewer.py
import json
from prompt_runtime import compose_prompt
from services.llm_client import safe_json_call
from review.scorer import (
    audit_character_names,
    validate_output_format,
    score_hook_density,
    merge_rule_issues,
)


def _build_review_prompt(stage_name, brief, draft, **kwargs):
    data = {
        "stage_name": stage_name,
        "story_brief": brief,
        "draft": draft,
        "genre": brief.get("genre", ""),
        "style": brief.get("style", ""),
        "core_conflict": brief.get("core_conflict", ""),
        "banned_items": brief.get("banned_items", []),
    }
    data.update(kwargs)
    return compose_prompt("review_report_json", data, mode=brief.get("mode"))


def render_text_review(review_json: dict) -> str:
    score = review_json.get("score", 0)
    passed = "通过" if review_json.get("passed") else "未通过"
    summary = review_json.get("summary", "")
    issues = review_json.get("blocking_issues") or []
    warnings = review_json.get("warnings") or []

    lines = [
        f"审核结论：{passed}",
        f"评分：{score}",
        f"摘要：{summary}",
        "",
        "必须修改项：",
    ]

    if issues:
        for idx, item in enumerate(issues, 1):
            lines.append(f"{idx}. [{item.get('code','')}] {item.get('message','')}；修复方向：{item.get('fix_direction','')}")
    else:
        lines.append("无")

    lines.append("")
    lines.append("提示项：")
    if warnings:
        for idx, item in enumerate(warnings, 1):
            lines.append(f"{idx}. [{item.get('code','')}] {item.get('message','')}；建议：{item.get('fix_direction','')}")
    else:
        lines.append("无")

    return "\n".join(lines).strip()


def review_character_bible(brief, draft, llm_call, selected_model):
    prompt = _build_review_prompt("character_bible", brief, draft)
    llm_review = safe_json_call(prompt, selected_model, "reviewer", llm_call=llm_call)
    rule_review = audit_character_names(draft, brief.get("review_strictness", "strict"))
    merged = merge_rule_issues(llm_review, rule_review)
    merged["text_report"] = render_text_review(merged)
    return merged


def review_plot_outline(brief, character_bible, plot_outline, llm_call, selected_model):
    prompt = _build_review_prompt("plot_outline", brief, plot_outline, character_bible=character_bible)
    llm_review = safe_json_call(prompt, selected_model, "reviewer", llm_call=llm_call)
    merged = merge_rule_issues(llm_review)
    merged["text_report"] = render_text_review(merged)
    return merged


def review_episode_plan(brief, character_bible, approved_outline, episode_plan, llm_call, selected_model):
    prompt = _build_review_prompt(
        "episode_plan",
        brief,
        episode_plan,
        character_bible=character_bible,
        approved_outline=approved_outline,
    )
    llm_review = safe_json_call(prompt, selected_model, "reviewer", llm_call=llm_call)
    format_review = validate_output_format(episode_plan, "episode_plan")
    merged = merge_rule_issues(llm_review, format_review)
    merged["text_report"] = render_text_review(merged)
    return merged


def review_episode_script(
    brief,
    character_bible,
    approved_plan,
    episode_no,
    current_episode_plan,
    episode_script,
    llm_call,
    selected_model,
):
    prompt = _build_review_prompt(
        "single_episode_script",
        brief,
        episode_script,
        character_bible=character_bible,
        approved_plan=approved_plan,
        current_episode_no=episode_no,
        current_episode_plan=current_episode_plan,
    )
    llm_review = safe_json_call(prompt, selected_model, "reviewer", llm_call=llm_call)
    format_review = validate_output_format(episode_script, "single_episode_script", episode_no=episode_no)
    hook_review = score_hook_density(episode_script, "single_episode_script")
    merged = merge_rule_issues(llm_review, format_review, hook_review)
    merged["text_report"] = render_text_review(merged)
    return merged


# 兼容旧 pipeline 的兜底函数
def review_artifacts(story_brief, character_bible, plot_outline, llm_call=None, selected_model=None):
    if llm_call is None or selected_model is None:
        return {
            "passed": True,
            "rewrite_required": False,
            "score": 80,
            "blocking_issues": [],
            "warnings": [],
            "summary": "旧兼容模式，未执行真实审核。",
            "text_report": "旧兼容模式，未执行真实审核。",
        }
    return review_plot_outline(story_brief, character_bible, plot_outline, llm_call, selected_model)