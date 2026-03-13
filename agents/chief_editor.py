import re
from datetime import datetime, timezone

DEFAULT_WORD_COUNT_WAN = 2.0

MAIN_CATEGORY_VOCAB = [
    "现代言情", "古代言情", "都市", "玄幻仙侠", "悬疑",
    "历史", "校园青春", "科幻末世", "奇幻", "职场", "衍生"
]

STYLE_TAG_VOCAB = [
    "女频短剧", "男频爽剧", "甜宠", "复仇", "逆袭", "高反转", "强钩子",
    "悬疑恋爱", "纯爱", "赛博朋克", "规则怪谈", "悬疑", "克苏鲁",
    "都市异能", "末日求生", "灵气复苏", "高武世界", "异世大陆",
    "东方玄幻", "谍战", "总裁", "多女主", "教授", "忠犬", "全能",
    "白切黑", "双学霸", "位尊权重", "作精", "大佬", "大小姐", "特工",
    "游戏主播", "神探", "宫廷侯爵", "皇帝", "将军", "毒医", "厨娘",
    "律师", "医生", "明星", "替身", "双面", "女频悬疑", "西方奇幻",
    "东方仙侠", "古风世情", "男频衍生", "女频衍生", "民国言情",
    "都市高武", "悬疑灵异", "悬疑脑洞", "抗战谍战", "青春甜宠", "双男主",
    "古言脑洞", "历史古代", "历史脑洞", "现言脑洞", "都市种田",
    "都市脑洞", "都市日常", "玄幻脑洞", "玄幻言情"
]

RESKIN_HINTS = [
    "参考", "参考作品", "按这个改", "照着这个改", "换皮", "仿照", "类似", "参考这个故事","模仿","参照","仿写"
]

FRAMEWORK_HINTS = [
    "框架", "提纲", "骨架", "设定如下", "按照下面结构", "我已经想好了", "章节安排", "结构", "架构"
]

def _normalize_word_count_wan(value):
    try:
        v = float(value)
        if v <= 0:
            return DEFAULT_WORD_COUNT_WAN
        return v
    except Exception:
        return DEFAULT_WORD_COUNT_WAN


def _format_word_count_text(word_count_wan):
    if word_count_wan <= 0:
        word_count_wan = DEFAULT_WORD_COUNT_WAN
    return f"{word_count_wan}万字（短篇默认）"


def _dedupe_keep_order(items):
    result = []
    seen = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _extract_by_vocab(text, vocab):
    hit = []
    for item in vocab:
        if item in text:
            hit.append(item)
    return _dedupe_keep_order(hit)


def _extract_banned_items(text):
    banned = []
    patterns = [
        r"不要([^，。,；;\n]+)",
        r"禁止([^，。,；;\n]+)",
        r"避开([^，。,；;\n]+)",
        r"不想要([^，。,；;\n]+)"
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            banned.append(m.strip())

    return _dedupe_keep_order(banned)


def _detect_mode_from_inputs(message, meta):
    """
    二次判断模式：
    1. reference_text 优先 -> reskin
    2. framework_text 次优先 -> framework
    3. 再按 message 关键词判断
    """
    reference_text = (meta.get("reference_text") or "").strip()
    framework_text = (meta.get("framework_text") or "").strip()
    msg = (message or "").strip()

    if reference_text:
        return "reskin"
    if framework_text:
        return "framework"

    if any(k in msg for k in FRAMEWORK_HINTS):
        return "framework"
    if any(k in msg for k in RESKIN_HINTS):
        return "reskin"

    return "free_generate"


def _guess_output_granularity(user_input: str, meta=None) -> str:
    text = (user_input or "").lower()
    meta = meta or {}

    try:
        episode_count = int(meta.get("episode_count") or 0)
    except Exception:
        episode_count = 0

    if any(k in text for k in ["场景资产", "场景表", "道具表", "场景拆解"]):
        return "scene_asset_extract"

    if any(k in text for k in ["多集", "连续输出", "整季剧本", "全集剧本", "批量剧本"]):
        return "multi_episode_script"

    if episode_count > 1:
        return "multi_episode_script"

    if any(k in text for k in ["单集", "这一集", "第1集", "第2集", "本集剧本"]):
        return "single_episode_script"

    if any(k in text for k in ["分集计划", "逐集计划", "10集计划", "集纲"]):
        return "episode_plan"

    return "outline"


def choose_delivery_mode(analysis: dict) -> str:
    granularity = (analysis.get("output_granularity") or "").strip().lower()
    valid = {
        "outline",
        "episode_plan",
        "single_episode_script",
        "multi_episode_script",
        "scene_asset_extract",
    }
    return granularity if granularity in valid else "outline"


def decide_next_action(stage_name: str, review_json: dict) -> str:
    if not isinstance(review_json, dict):
        return "rewrite"

    if review_json.get("passed"):
        return "approve"

    if review_json.get("rewrite_required", True):
        return "rewrite"

    return "approve"


def build_rewrite_instruction(stage_name: str, review_json: dict) -> str:
    if not isinstance(review_json, dict):
        return f"请按{stage_name}目标重新生成，修复结构、格式与逻辑问题。"

    summary = (review_json.get("summary") or "").strip()
    issues = review_json.get("blocking_issues") or []
    fix_lines = []

    for idx, item in enumerate(issues, 1):
        if not isinstance(item, dict):
            continue
        code = item.get("code", "")
        msg = item.get("message", "")
        fix = item.get("fix_direction", "")
        fix_lines.append(f"{idx}. [{code}] {msg}；修复方向：{fix}")

    joined = "\n".join(fix_lines).strip()
    if joined:
        return f"{summary}\n请严格按以下问题逐条返工：\n{joined}"

    return summary or f"请按{stage_name}阶段要求返工，保留正确部分，修复未通过项。"


def analyze_requirements(message, meta):
    """
    requirement analyzer（规则版）：
    先满足你现在的系统要求：
    - 支持 reference_text / framework_text 直接驱动模式
    - 用户写得少时自动补齐
    - 不依赖额外模型，先确保稳定
    """
    msg = (message or "").strip()
    meta = meta or {}

    word_count_wan = _normalize_word_count_wan(meta.get("word_count_wan"))

    reference_text = (meta.get("reference_text") or "").strip()
    framework_text = (meta.get("framework_text") or "").strip()

    mode = _detect_mode_from_inputs(msg, meta)

    main_categories = _extract_by_vocab(msg, MAIN_CATEGORY_VOCAB)
    style_tags = _extract_by_vocab(msg, STYLE_TAG_VOCAB)
    banned_items = _extract_banned_items(msg)

    # 如果上传/网页读取了 reference_text，但用户正文里没写清分类，就做一个更稳的默认
    if not main_categories:
        if mode == "reskin":
            main_categories = ["都市"]
        else:
            main_categories = ["都市"]

    if not style_tags:
        if mode == "reskin":
            style_tags = ["强钩子", "高反转"]
        else:
            style_tags = ["强钩子", "高反转"]

    return {
        "mode": mode,
        "main_categories": main_categories,
        "style_tags": style_tags,
        "core_conflict": msg or "用户未提供明确核心冲突，由系统自由发挥",
        "tone": "偏商业化、节奏快、短篇可执行",
        "reference_text": reference_text if mode == "reskin" else "",
        "framework_text": framework_text if mode == "framework" else "",
        "banned": "、".join(banned_items),
        "output_granularity": _guess_output_granularity(msg),
        "word_count_wan": word_count_wan,
        "episode_count": int(meta.get("episode_count") or 10),
        "current_episode_no": int(meta.get("current_episode_no") or 1),
        "review_strictness": (meta.get("review_strictness") or "strict").strip().lower(),
        "banned_items": banned_items
    }


def build_story_brief(payload, mode):
    """
    总编剧主入口：
    pipeline 会先传一个粗 mode 进来，
    这里再做 requirement analyzer，并覆盖成最终 mode。
    """
    meta = payload.get("meta", {}) or {}
    message = (payload.get("message") or "").strip()

    analysis = analyze_requirements(message, meta)
    final_mode = analysis.get("mode") or mode or "free_generate"

    return {
        "mode": final_mode,
        "user_message": message,
        "word_count_wan": analysis["word_count_wan"],
        "word_count": _format_word_count_text(analysis["word_count_wan"]),

        "main_categories": analysis["main_categories"],
        "style_tags": analysis["style_tags"],
        "core_conflict": analysis["core_conflict"],
        "tone": analysis["tone"],

        "genre": "、".join(analysis["main_categories"]),
        "style": "、".join(analysis["style_tags"]),

        "reference_text": analysis["reference_text"],
        "framework_text": analysis["framework_text"],
        "banned": analysis["banned"],
        "output_granularity": analysis["output_granularity"],

        "analysis_trace": {
            "mode": final_mode,
            "main_categories": analysis["main_categories"],
            "style_tags": analysis["style_tags"],
            "core_conflict": analysis["core_conflict"]
        },

        "created_at": datetime.now(timezone.utc).isoformat(),
        "episode_count": analysis["episode_count"],
        "current_episode_no": analysis["current_episode_no"],
        "review_strictness": analysis["review_strictness"],
        "banned_items": analysis["banned_items"]
    }