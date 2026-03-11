import os
import re
import json
import logging
from bs4 import BeautifulSoup
from pypdf import PdfReader
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

# =========================
# 基础配置
# =========================
DEFAULT_WORD_COUNT_WAN = 2.0

API = os.getenv("API", "ollama").lower()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").strip()

DEEPSEEK_HOST = os.getenv("DEEPSEEK_HOST", "").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip()

GEMINI_HOST = os.getenv("GEMINI_HOST", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()

# 主分类词表（可继续扩充）
MAIN_CATEGORY_VOCAB = [
    "现代言情", "古代言情", "都市", "玄幻仙侠", "悬疑",
    "历史", "校园青春", "科幻末世", "奇幻", "职场", "衍生"
]

# 风格标签词表（可继续扩充）
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
    "参考", "参考作品", "按这个改", "照着这个改", "换皮", "仿照", "类似", "参考这个故事"
]

FRAMEWORK_HINTS = [
    "框架", "提纲", "骨架", "设定如下", "按照下面结构", "我已经想好了", "章节安排"
]


# =========================
# 工具函数
# =========================
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
    """
    从用户输入里提取“不要/禁止/避开”之类的禁用项
    """
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


def _detect_mode_from_message(message):
    msg = (message or "").strip()

    is_reskin = any(k in msg for k in RESKIN_HINTS)
    is_framework = any(k in msg for k in FRAMEWORK_HINTS)

    # 如果两者都命中，优先认为是框架创作（因为更明确）
    if is_framework:
        return "framework", is_reskin, is_framework
    if is_reskin:
        return "reskin", is_reskin, is_framework
    return "free_generate", is_reskin, is_framework


def _guess_output_granularity(message):
    msg = (message or "").strip()
    if any(k in msg for k in ["完整剧本", "正文", "完整小说", "详细正文"]):
        return "script"
    return "outline"


def _rule_based_requirement_analysis(message, word_count_wan):
    """
    规则兜底分析：
    当 LLM 分析失败时，至少给出可用结构
    """
    msg = (message or "").strip()

    mode, is_reskin, is_framework = _detect_mode_from_message(msg)

    main_categories = _extract_by_vocab(msg, MAIN_CATEGORY_VOCAB)
    style_tags = _extract_by_vocab(msg, STYLE_TAG_VOCAB)
    banned = _extract_banned_items(msg)

    # 如果一个分类都没抓到，给保守默认值
    if not main_categories:
        # 简单兜底：优先给“都市”
        main_categories = ["都市"]

    # 如果一个风格都没抓到，给内部常用默认
    if not style_tags:
        style_tags = ["强钩子", "高反转"]

    # 核心冲突：先直接用原句做保底
    core_conflict = msg

    return {
        "mode": mode,
        "main_categories": main_categories,
        "style_tags": style_tags,
        "core_conflict": core_conflict,
        "tone": "偏商业化、节奏快、短篇可执行",
        "is_reskin": is_reskin,
        "is_framework": is_framework,
        "reference_text": msg if is_reskin else "",
        "framework_text": msg if is_framework else "",
        "banned": "、".join(banned),
        "output_granularity": _guess_output_granularity(msg),
        "word_count_wan": word_count_wan
    }


def _extract_json_from_text(text):
    """
    从模型返回文本中抽取 JSON 对象
    """
    if not text:
        return None

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 尝试提取 {...}
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None

    json_text = match.group(0)
    try:
        return json.loads(json_text)
    except Exception:
        return None


def _call_llm_json(prompt):
    """
    调模型，要求返回 JSON；失败时抛异常
    """
    messages = [
        {
            "role": "system",
            "content": "你是内部剧本需求分析器。你的任务是从用户输入中提取创作需求，并补全缺失字段。必须只返回 JSON。"
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    current_api = API

    if current_api == "deepseek":
        response = requests.post(
            DEEPSEEK_HOST,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 4096,
                "stream": False
            },
            timeout=180
        )
    elif current_api == "gemini":
        response = requests.post(
            GEMINI_HOST,
            headers={
                "Authorization": f"Bearer {GEMINI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": GEMINI_MODEL,
                "messages": messages,
                "temperature": 0.3,
                "stream": False
            },
            timeout=180
        )
    else:
        response = requests.post(
            OLLAMA_HOST,
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False
            },
            timeout=180
        )

    if response.status_code != 200:
        raise Exception(f"LLM 调用失败: {response.status_code} - {response.text}")

    data = response.json()
    content = ""

    if current_api == "deepseek":
        content = data["choices"][0]["message"]["content"]
    elif current_api == "gemini":
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
        else:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
    else:
        content = data["message"]["content"]

    parsed = _extract_json_from_text(content)
    if not parsed:
        raise Exception("需求分析器未返回可解析 JSON")
    return parsed


def _llm_requirement_analysis(message, word_count_wan):
    prompt = f"""
请根据下面的用户输入，提取并补全剧本需求。
这是内部创作系统，不需要迎合大众化输入；请优先保证结构化、可执行、便于后续人物编剧和剧情编剧使用。

【用户输入】
{message}

【字数要求】
{word_count_wan}万字

请严格只输出 JSON，不要输出解释，不要输出 Markdown。
JSON 字段要求如下：
{{
  "mode": "free_generate | reskin | framework",
  "main_categories": ["主分类1", "主分类2"],
  "style_tags": ["风格标签1", "风格标签2"],
  "core_conflict": "一句话核心冲突",
  "tone": "整体风格和语气说明",
  "is_reskin": false,
  "is_framework": false,
  "reference_text": "",
  "framework_text": "",
  "banned": "",
  "output_granularity": "outline | script"
}}

规则：
1. 如果用户写得很少，请你合理补全，不要返回空数组
2. 允许多分类，但必须有主次
3. 如果判断是参考换皮模式，请把原输入中与参考相关的部分写入 reference_text
4. 如果判断是框架创作模式，请把原输入中与框架相关的部分写入 framework_text
5. 如果没有明确完整正文需求，output_granularity 默认给 outline
6. main_categories 尽量从以下大类中选：现代言情、古代言情、都市、玄幻仙侠、悬疑、历史、校园青春、科幻末世、奇幻、职场、衍生
7. style_tags 可结合商业短篇倾向补充，例如：强钩子、高反转、复仇、甜宠、悬疑恋爱、都市异能、女频悬疑等
"""
    return _call_llm_json(prompt)


def analyze_requirements(message, word_count_wan):
    """
    统一入口：
    先尝试用 LLM 做需求分析；
    如果失败，则使用规则兜底。
    """
    try:
        result = _llm_requirement_analysis(message, word_count_wan)
        # 基础清洗
        result["main_categories"] = _dedupe_keep_order(result.get("main_categories", []))
        result["style_tags"] = _dedupe_keep_order(result.get("style_tags", []))

        if not result["main_categories"]:
            result["main_categories"] = ["都市"]
        if not result["style_tags"]:
            result["style_tags"] = ["强钩子", "高反转"]

        result["word_count_wan"] = word_count_wan
        return result
    except Exception as e:
        logging.warning(f"LLM 需求分析失败，启用规则兜底：{str(e)}")
        return _rule_based_requirement_analysis(message, word_count_wan)


# =========================
# 外部调用主函数
# =========================
def build_story_brief(payload, mode):
    """
    总编剧主入口：
    1. 读取前端极简输入
    2. 先做 requirement analyzer
    3. 再生成统一结构的 story_brief
    """
    meta = payload.get("meta", {}) or {}
    message = (payload.get("message") or "").strip()
    word_count_wan = _normalize_word_count_wan(meta.get("word_count_wan"))

    # requirement analyzer
    analysis = analyze_requirements(message, word_count_wan)

    # 用 analyzer 结果覆盖旧 mode
    final_mode = analysis.get("mode") or mode or "free_generate"

    story_brief = {
        "mode": final_mode,
        "user_message": message,
        "word_count_wan": word_count_wan,
        "word_count": _format_word_count_text(word_count_wan),

        # requirement analyzer 产物
        "main_categories": analysis.get("main_categories", []),
        "style_tags": analysis.get("style_tags", []),
        "core_conflict": analysis.get("core_conflict", message),
        "tone": analysis.get("tone", "偏商业化、节奏快、短篇可执行"),

        "is_reskin": bool(analysis.get("is_reskin")),
        "is_framework": bool(analysis.get("is_framework")),
        "reference_text": (analysis.get("reference_text") or "").strip(),
        "framework_text": (analysis.get("framework_text") or "").strip(),
        "banned": (analysis.get("banned") or "").strip(),
        "output_granularity": (analysis.get("output_granularity") or "outline").strip(),

        # 兼容旧 prompt 的字段
        "genre": "、".join(analysis.get("main_categories", [])),
        "style": "、".join(analysis.get("style_tags", [])),

        # trace 用
        "analysis_trace": {
            "mode": final_mode,
            "main_categories": analysis.get("main_categories", []),
            "style_tags": analysis.get("style_tags", []),
            "core_conflict": analysis.get("core_conflict", message)
        },

        "created_at": datetime.now(timezone.utc).isoformat()
    }

    return story_brief