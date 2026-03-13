import os
import json
import re
from typing import Any, Dict, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")

PROMPT_MANIFEST = {
    "input_normalizer": "core/input_normalizer.txt",
    "content_check": "core/source_asset_extract.txt",
    "source_asset_extract": "core/source_asset_extract.txt",
    "characters": "core/character_bible_json.txt",
    "character_bible": "core/character_bible_json.txt",

    "outline": "core/story_outline.txt",
    "episode_plan": "core/episode_plan.txt",
    "single_episode_script": "core/single_episode_script.txt",
    "scene_asset_extract": "core/scene_asset_extract.txt",

    "review_report": "core/review_report.txt",
    "review_report_json": "core/review_report_json.txt",
    "five_episode_consistency_review": "core/five_episode_consistency_review.txt",

    "character_rewrite": "core/character_rewrite.txt",
    "outline_rewrite": "core/outline_rewrite.txt",
    "episode_plan_rewrite": "core/episode_plan_rewrite.txt",
    "single_episode_rewrite": "core/single_episode_rewrite.txt",

    "final_rewrite": "core/final_rewrite.txt",
    "chapter_script": "core/single_episode_script.txt",
}

LEGACY_FALLBACK = {
    "characters": "characters.txt",
    "outline": "outline.txt",
    "chapter_script": "chapter_script.txt",
    "content_check": "content_check.txt",
}

MODEL_MANIFEST = {
    "reskin_longform": "modes/reskin_longform.txt",
    "short_drama_cn": "modes/short_drama_cn.txt",
    "novel_serial": "modes/novel_serial.txt",
    "": None,
    None: None,
}

ALIASES = {
    "character": "character_bible",
    "character_bible_json": "characters",
    "story_outline": "outline",
    "review": "review_report",
    "final": "final_rewrite",
    "single_episode": "chapter_script",
}


def normalize_output_granularity(value: Optional[str]) -> str:
    value = (value or "").strip().lower()
    mapping = {
        "outline": "outline",
        "story_outline": "outline",
        "episode_plan": "episode_plan",
        "episode": "episode_plan",
        "episodes": "episode_plan",
        "series": "episode_plan",
        "single_episode_script": "single_episode_script",
        "single_episode": "single_episode_script",
        "multi_episode_script": "multi_episode_script",
        "multi_episode": "multi_episode_script",
        "batch_episode_script": "multi_episode_script",
        "scene_asset_extract": "scene_asset_extract",
    }
    return mapping.get(value, "outline")


def normalize_mode(value: Optional[str]) -> str:
    value = (value or "").strip().lower()
    if value in MODEL_MANIFEST:
        return value
    return ""


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


WORKFLOW_ONLY_GRANULARITIES = {"multi_episode_script"}

def resolve_prompt_path(task_name: str, granularity: Optional[str] = None) -> str:
    task_name = ALIASES.get(task_name, task_name)
    conf = PROMPT_MANIFEST.get(task_name)
    if conf is None:
        raise ValueError(f"未注册的 prompt task: {task_name}")

    if isinstance(conf, dict):
        granularity = normalize_output_granularity(granularity)

        if granularity in WORKFLOW_ONLY_GRANULARITIES:
            raise ValueError(
                f"{granularity} 是 workflow mode，不能直接解析为单个 prompt 文件。"
            )

        rel_path = conf.get(granularity) or conf.get("outline")
    else:
        rel_path = conf

    full_path = os.path.join(PROMPTS_DIR, rel_path)
    if os.path.exists(full_path):
        return full_path

    fallback = LEGACY_FALLBACK.get(task_name)
    if fallback:
        legacy_path = os.path.join(PROMPTS_DIR, fallback)
        if os.path.exists(legacy_path):
            return legacy_path

    raise FileNotFoundError(f"找不到 prompt 文件: {full_path}")


def load_prompt_text(task_name: str, granularity: Optional[str] = None) -> str:
    path = resolve_prompt_path(task_name, granularity=granularity)
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def load_model_profile(mode: Optional[str]) -> str:
    mode = normalize_mode(mode)
    rel_path = MODEL_MANIFEST.get(mode)
    if not rel_path:
        return ""

    full_path = os.path.join(PROMPTS_DIR, rel_path)
    if not os.path.exists(full_path):
        return ""

    with open(full_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def build_structured_input_block(data: Dict[str, Any]) -> str:
    field_labels = [
        ("title", "标题"),
        ("title_hint", "标题方向"),
        ("genre", "题材"),
        ("subgenre", "细分题材"),
        ("tone", "风格气质"),
        ("style", "写作风格"),
        ("format", "作品形态"),
        ("target_length", "目标篇幅"),
        ("word_count", "字数"),
        ("character_count", "角色数量"),
        ("episode_count", "集数"),
        ("current_episode_no", "当前集数"),
        ("generated_episode_count", "已生成集数"),
        ("episode_target_words", "单集目标字数"),
        ("output_granularity", "输出粒度"),
        ("additional_requirements", "用户原始需求"),
        ("framework_text", "框架内容"),
        ("reference_text", "参考内容"),
        ("banned_items", "禁止项"),
        ("must_keep", "必须保留"),
        ("core_conflict", "主冲突"),
        ("protagonist_core", "主角核心"),
        ("antagonist_core", "对手核心"),
        ("source_text", "源文本"),
        ("background", "背景设定"),
        ("knowledge", "知识库"),
        ("history", "已有内容/人物设定"),
        ("content", "正文/大纲内容"),
        ("review_report", "审核报告"),
        ("uncertainty_notes", "不确定项"),
        ("previous_state", "上一集状态"),
        ("current_episode_plan", "当前集计划"),
        ("stage_name", "审核阶段"),
        ("approved_outline", "已通过总纲"),
        ("approved_plan", "已通过分集计划"),
        ("episode_batch", "当前五集正文"),
        ("batch_range", "审核批次范围"),
        ("previous_batch_review", "上一轮批次审核"),
        ("draft", "待审核正文"),
    ]

    lines = ["# Structured Input"]
    for key, label in field_labels:
        value = data.get(key)
        if value in (None, "", [], {}):
            continue
        lines.append("")
        lines.append(f"## {label}")
        lines.append(_safe_text(value))
    return "\n".join(lines).strip()


def compose_prompt(task_name: str, data: Dict[str, Any], mode: Optional[str] = None) -> str:
    granularity = data.get("output_granularity")
    core_prompt = load_prompt_text(task_name, granularity=granularity)
    model_profile = load_model_profile(mode or data.get("mode"))
    input_block = build_structured_input_block(data)

    parts = [core_prompt]
    if model_profile:
        parts.append("\n\n# Model Profile\n" + model_profile)
    parts.append("\n\n" + input_block)

    return "".join(parts).strip()


def extract_json_from_text(text: str) -> Any:
    text = (text or "").strip()

    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
    if not match:
        raise ValueError("模型输出中未找到可解析 JSON")

    return json.loads(match.group(1))