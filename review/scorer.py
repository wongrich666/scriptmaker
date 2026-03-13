# review/scorer.py
import json
import re
from typing import Any, Dict, List


FORBIDDEN_FULL_NAMES = {
    "柳如烟", "林薇", "苏晴雨", "苏沐雪", "夏若雪", "楚梦瑶",
    "白若溪", "秦舒然", "唐雪", "江晚吟", "沈若冰", "叶清妍",
    "苏晚晴", "苏若依", "楚菲", "楚云容", "林皓雪", "沐雨心", "叶婉清",
}

RISKY_TOKENS = {
    "若", "雪", "瑶", "溪", "妍", "柔", "薇",
    "渊", "宸", "冽", "寒", "辰", "麟", "战", "琛",
}

HOOK_KEYWORDS = {
    "single_episode_script": ["当众", "曝光", "直播", "退婚", "报警", "下跪", "抓住", "砸", "冲进", "摔", "爆出", "威胁", "离婚"],
    "episode_plan": ["爆点", "反转", "公开羞辱", "代价", "钩子"],
}


def _coerce_to_rows(character_data: Any) -> List[Dict[str, Any]]:
    if isinstance(character_data, list):
        return [x for x in character_data if isinstance(x, dict)]

    if isinstance(character_data, dict):
        if isinstance(character_data.get("characters"), list):
            return [x for x in character_data["characters"] if isinstance(x, dict)]
        return [character_data]

    text = (character_data or "").strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        return _coerce_to_rows(parsed)
    except Exception:
        pass

    rows = []
    for line in text.splitlines():
        m = re.search(r"(?:姓名|名字)[:：]\s*([^\s,，;；]+)", line)
        if m:
            rows.append({"name": m.group(1)})
    return rows


def audit_character_names(character_data: Any, strictness: str = "strict") -> Dict[str, Any]:
    rows = _coerce_to_rows(character_data)
    seen = {}
    blocking_issues = []
    warnings = []

    for row in rows:
        name = str(row.get("name") or row.get("姓名") or "").strip()
        if not name:
            continue

        seen[name] = seen.get(name, 0) + 1

        if name in FORBIDDEN_FULL_NAMES:
            blocking_issues.append({
                "code": "NAME_BLACKLIST_HIT",
                "message": f"角色名命中黑名单：{name}",
                "fix_direction": "请更换为更生活化、非模板化姓名",
            })

        hit_tokens = [tok for tok in RISKY_TOKENS if tok in name]
        if hit_tokens:
            warnings.append({
                "code": "NAME_TEMPLATE_RISK",
                "message": f"角色名存在模板化风险：{name}",
                "fix_direction": f"尽量避免高频模板 token：{','.join(hit_tokens)}",
            })

    for name, count in seen.items():
        if count > 1:
            blocking_issues.append({
                "code": "DUPLICATE_NAME",
                "message": f"存在撞名：{name}",
                "fix_direction": "请保证同一项目角色名不重复",
            })

    passed = not blocking_issues
    if strictness == "very_strict" and warnings:
        passed = False

    score_adjustment = -10 * len(blocking_issues) - 3 * len(warnings)

    return {
        "passed": passed,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "score_adjustment": score_adjustment,
    }


def validate_output_format(text: str, output_granularity: str, episode_no: int = None) -> Dict[str, Any]:
    text = (text or "").strip()
    blocking_issues = []
    warnings = []

    if output_granularity == "single_episode_script":
        first_line = text.splitlines()[0].strip() if text.splitlines() else ""
        if not re.match(r"^第\s*\d+\s*集[：:]", first_line):
            blocking_issues.append({
                "code": "SCRIPT_HEADER_INVALID",
                "message": "单集剧本首行不是“第X集：标题”格式",
                "fix_direction": "第一行必须改成：第X集：标题",
            })

        forbidden_prefixes = ["项目定位", "最终稿总结", "以下是结果", "修订重点", "策划说明"]
        head = text[:240]
        if any(x in head for x in forbidden_prefixes):
            blocking_issues.append({
                "code": "NON_SCRIPT_PREFIX",
                "message": "单集输出带了说明性前缀，不是纯剧本",
                "fix_direction": "删除策划/总结/说明类前缀，只保留剧本正文",
            })

        if "场景：" not in text and "〖开场〗" not in text:
            warnings.append({
                "code": "SCRIPT_FORMAT_WEAK",
                "message": "单集剧本格式化标签较弱",
                "fix_direction": "建议补足场景标签、动作线和反转标签",
            })

    if output_granularity == "episode_plan":
        if "第1集" not in text and "第 1 集" not in text:
            warnings.append({
                "code": "EPISODE_PLAN_HEADER_WEAK",
                "message": "分集计划没有清晰的集次标题",
                "fix_direction": "建议使用“第1集/第2集”结构清晰分段",
            })

    return {
        "passed": not blocking_issues,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "score_adjustment": -8 * len(blocking_issues) - 2 * len(warnings),
    }


def score_hook_density(text: str, output_granularity: str) -> Dict[str, Any]:
    text = (text or "").strip()
    head = text[:260]
    keywords = HOOK_KEYWORDS.get(output_granularity, [])
    hit_count = sum(1 for k in keywords if k in head)

    warnings = []
    if output_granularity == "single_episode_script" and hit_count == 0:
        warnings.append({
            "code": "HOOK_TOO_WEAK",
            "message": "开场强事件不足，钩子偏弱",
            "fix_direction": "前8行内加入明确的具体事件型冲突",
        })

    return {
        "passed": True,
        "blocking_issues": [],
        "warnings": warnings,
        "score_adjustment": -2 * len(warnings),
    }


def merge_rule_issues(llm_review: Dict[str, Any], *rule_reviews: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(llm_review or {})
    merged.setdefault("blocking_issues", [])
    merged.setdefault("non_blocking_issues", [])
    merged.setdefault("warnings", [])
    merged.setdefault("score", 80)
    merged.setdefault("rewrite_required", False)
    merged.setdefault("passed", True)

    for rule in rule_reviews:
        if not isinstance(rule, dict):
            continue
        merged["blocking_issues"].extend(rule.get("blocking_issues") or [])
        merged["warnings"].extend(rule.get("warnings") or [])
        merged["score"] = int(merged.get("score", 80)) + int(rule.get("score_adjustment") or 0)

    if merged["blocking_issues"]:
        merged["passed"] = False
        merged["rewrite_required"] = True

    return merged