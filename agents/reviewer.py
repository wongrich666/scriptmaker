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


def review_five_episode_consistency(
    brief,
    character_bible,
    approved_outline,
    approved_plan,
    episode_batch,
    batch_start,
    batch_end,
    llm_call,
    selected_model,
    previous_batch_review=None,
):
    """
    对连续 5 集（或最后不足 5 集的一批）进行阶段性连贯性总审。
    返回结构与现有 review_* 保持兼容，核心字段仍然包括：
    passed / rewrite_required / score / summary / blocking_issues / text_report
    """

    batch_text = "\n\n".join(
        [
            f"===== 第{ep.get('episode_no', '?')}集 =====\n{ep.get('chapter_script', '')}"
            for ep in episode_batch
            if isinstance(ep, dict)
        ]
    ).strip()

    data = {
        "stage_name": "five_episode_consistency_review",
        "story_brief": brief,
        "character_bible": character_bible,
        "approved_outline": approved_outline,
        "approved_plan": approved_plan,
        "episode_batch": batch_text,
        "batch_range": f"第{batch_start}-{batch_end}集",
        "previous_batch_review": previous_batch_review or "",
        "output_granularity": "five_episode_consistency_review",
        "genre": brief.get("genre", ""),
        "style": brief.get("style", ""),
        "core_conflict": brief.get("core_conflict", ""),
        "banned_items": brief.get("banned_items", []),
    }

    prompt = compose_prompt(
        "five_episode_consistency_review",
        data,
        mode=brief.get("mode"),
    )

    try:
        llm_review = safe_json_call(
            prompt,
            selected_model,
            "reviewer",
            llm_call=llm_call,
        )
    except Exception as e:
        llm_review = {
            "passed": False,
            "rewrite_required": True,
            "score": 0,
            "stage": "five_episode_consistency_review",
            "summary": f"五集连贯性总审返回了非法 JSON：{e}",
            "blocking_issues": [
                {
                    "code": "INVALID_REVIEW_JSON",
                    "message": "审核模型没有返回合法 JSON。",
                    "fix_direction": "请重试本批次总审，或缩短批次输入长度。"
                }
            ],
            "non_blocking_issues": [],
            "rewrite_instruction": "请重新执行该批次总审。"
        }

    # 五集总审先不叠加名字/单集格式/钩子密度等单集规则，
    # 避免误伤；这里只保留 LLM 总审结果即可。
    merged = merge_rule_issues(llm_review)

    # 给文本展示层补一个更明确的标题
    batch_label = f"第{batch_start}-{batch_end}集"
    merged["text_report"] = (
        f"【五集连贯性总审：{batch_label}】\n"
        + render_text_review(merged)
    )

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