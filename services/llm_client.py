# services/llm_client.py
import json
import re
from typing import Any, Callable, Dict


ROLE_SYSTEM_PROMPTS = {
    "chief_editor": "你是总编剧，负责统一创作目标、识别任务类型、决定下一步动作，并根据审核结果下达返工指令。",
    "writer_a": "你是人物编剧，只负责角色命名、人物设定、人物关系与人物戏剧功能，不负责写整集正文。",
    "writer_b": "你是剧情编剧，负责剧情大纲、分集计划和单集生产格式剧本，必须高密度推进冲突与反转。",
    "reviewer": "你是结构化审核官，只负责审稿，不负责润色。你必须输出可机读的审核结果，明确通过或打回。",
}


def build_system_prompt(role: str) -> str:
    role = (role or "").strip().lower()
    return ROLE_SYSTEM_PROMPTS.get(role, "你是专业的剧本创作智能体。")


def call_agent(
    prompt: str,
    selected_model: str,
    role: str,
    *,
    llm_call: Callable[..., str],
    temperature: float = 0.7,
    max_tokens: int = 8192,
) -> str:
    system_prompt = build_system_prompt(role)
    return llm_call(
        prompt,
        selected_model=selected_model,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _extract_json_block(text: str) -> str:
    text = (text or "").strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
    if fence_match:
        return fence_match.group(1).strip()

    first_brace = text.find("{")
    first_bracket = text.find("[")
    starts = [x for x in [first_brace, first_bracket] if x >= 0]
    if not starts:
        raise ValueError("模型返回中没有找到 JSON 结构")

    start = min(starts)
    candidate = text[start:].strip()

    # 尝试裁剪到最后一个 } 或 ]
    end_obj = candidate.rfind("}")
    end_arr = candidate.rfind("]")
    end = max(end_obj, end_arr)
    if end >= 0:
        candidate = candidate[: end + 1]

    return candidate.strip()


def safe_json_call(
    prompt: str,
    selected_model: str,
    role: str,
    *,
    llm_call: Callable[..., str],
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    raw = call_agent(
        prompt,
        selected_model,
        role,
        llm_call=llm_call,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    raw_json = _extract_json_block(raw)
    data = json.loads(raw_json)
    if not isinstance(data, dict):
        raise ValueError("审核结果必须是 JSON 对象")
    return data