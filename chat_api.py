# ============================================================
# Chat MVP API（问题2）作用与操作说明
# ============================================================
# 1. 这版是 MVP，不是最终版
# 2. task / trace 暂时不落库
# 3. 主要目的是先把聊天入口打通
# 4. 后续可以把 CHAT_TASK_STORE 改成数据库表：
#    conversation_session / generation_task / agent_trace 等
# 5. 后续也可以把“人物 / 剧情 / 审核”从 chat_api.py 再拆到
#    orchestrator/、agents/、review/、services/ 目录中
# ============================================================
import uuid
import threading
import traceback
import logging
import os
import json
import re
import requests
import time

import store
from requests.adapters import HTTPAdapter
from requests.exceptions import ChunkedEncodingError, ConnectionError as RequestsConnectionError, RequestException
from urllib3.util.retry import Retry
from datetime import datetime, timezone
from flask import current_app
from prompt_runtime import (
    compose_prompt,
    extract_json_from_text,
    resolve_prompt_path,
    normalize_output_granularity,
)
from urllib.parse import urlparse
from models import CharacterModel, ChapterModel, ScriptModel, db
from flask import Blueprint, request, jsonify, session
from flask_login import login_required, current_user
from io import BytesIO
from werkzeug.utils import secure_filename
from bs4 import BeautifulSoup
from pypdf import PdfReader

api = Blueprint('api', __name__)

# 设置Ollama服务器地址
from dotenv import load_dotenv

# 强制从.env文件加载环境变量，覆盖已存在的环境变量
load_dotenv(override=True)

# 获取环境变量
API = os.getenv('API')
OLLAMA_HOST = os.getenv('OLLAMA_HOST')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL')
DEEPSEEK_HOST = os.getenv('DEEPSEEK_HOST')
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = os.getenv('GEMINI_MODEL')
GEMINI_HOST = os.getenv('GEMINI_HOST')

ALLOWED_REFERENCE_EXTENSIONS = {"pdf", "txt", "md"}
MAX_REFERENCE_TEXT_CHARS = 20000


def parse_template_fields(template):
    """解析模板中的字段"""
    # 使用正则表达式匹配 {field_name} 格式的字段
    pattern = r'\{([^}]+)\}'
    fields = re.findall(pattern, template)
    return list(set(fields))  # 去重


def load_prompt_template(field_name):
    """加载提示词模板"""
    prompt_file = os.path.join('prompts', f'{field_name}.txt')
    if not os.path.exists(prompt_file):
        raise FileNotFoundError(f'提示词模板文件 {prompt_file} 不存在')

    with open(prompt_file, 'r', encoding='utf-8') as f:
        return f.read()


def _looks_like_openai_compatible_host(host):
    host = (host or "").lower()
    return ("zenmux.ai" in host) or ("api/v1" in host) or ("chat/completions" in host)


def _build_messages(system_prompt, prompt):
    return [
        {
            'role': 'system',
            'content': system_prompt
        },
        {
            'role': 'user',
            'content': prompt
        }
    ]


def _clean_model_content(content):
    content = content or ""
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
    return content.strip()


def _extract_json_from_model_output(text):
    text = (text or "").strip()

    # 去掉代码块包裹
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # 先直接解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 再尝试从正文中提取 JSON 数组或对象
    match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
    if not match:
        raise ValueError("模型返回中未找到有效 JSON 内容")

    return json.loads(match.group(1))


def _normalize_banned_items(raw_value):
    if isinstance(raw_value, list):
        return [str(x).strip() for x in raw_value if str(x).strip()]

    text = str(raw_value or "").strip()
    if not text:
        return []

    parts = re.split(r"[\n;,，；]+", text)
    cleaned = []
    for item in parts:
        item = item.strip().lstrip("-").lstrip("•").strip()
        if item:
            cleaned.append(item)
    return cleaned


def _normalize_chat_meta(meta):
    meta = dict(meta or {})

    try:
        raw_word_count = meta.get("word_count_wan", meta.get("word_count", 2))
        word_count_wan = float(raw_word_count)
    except Exception:
        word_count_wan = 2.0

    try:
        raw_episode_count = meta.get("episode_count", 10)
        episode_count = int(raw_episode_count or 10)
        if episode_count <= 0:
            episode_count = 10
    except Exception:
        episode_count = 10

    try:
        raw_current_episode_no = meta.get("current_episode_no", 1)
        current_episode_no = int(raw_current_episode_no or 1)
        if current_episode_no <= 0:
            current_episode_no = 1
    except Exception:
        current_episode_no = 1

    return {
        "word_count_wan": word_count_wan,
        "genre": str(meta.get("genre") or "").strip(),
        "style": str(meta.get("style") or "").strip(),
        "output_granularity": normalize_output_granularity(meta.get("output_granularity")),
        "reference_text": str(meta.get("reference_text") or "").strip(),
        "framework_text": str(meta.get("framework_text") or "").strip(),
        "banned_items": _normalize_banned_items(meta.get("banned") or meta.get("banned_items")),
        "mode": str(meta.get("mode") or "").strip(),
        "episode_count": episode_count,
        "current_episode_no": current_episode_no,
    }


def _build_chat_prompt_data(user_message, word_count_wan, meta, **kwargs):
    data = {
        "additional_requirements": user_message,
        "word_count": word_count_wan,
        "target_length": f"{word_count_wan}万字",
        "genre": meta.get("genre", ""),
        "style": meta.get("style", ""),
        "output_granularity": meta.get("output_granularity", "outline"),
        "reference_text": meta.get("reference_text", ""),
        "framework_text": meta.get("framework_text", ""),
        "banned_items": meta.get("banned_items", []),
    }
    data.update(kwargs)
    return data


def _build_http_session():
    """
    构建更稳的 requests Session：
    1. 忽略系统代理环境变量，避免莫名其妙走到坏掉的代理
    2. 自动重试临时网络错误
    3. 关闭长连接复用带来的脏连接问题
    """
    http_session = requests.Session()
    http_session.trust_env = False  # 关键：忽略 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    http_session.mount("http://", adapter)
    http_session.mount("https://", adapter)
    return http_session


def _build_single_episode_script_prompt(
    user_message,
    word_count_wan,
    character_bible,
    current_episode_plan,
    current_episode_no,
    meta,
):
    data = _build_chat_prompt_data(
        user_message,
        word_count_wan,
        meta,
        history=character_bible,
        current_episode_plan=current_episode_plan,
        current_episode_no=current_episode_no,
        generated_episode_count=meta.get("generated_episode_count"),
        episode_target_words=meta.get("episode_target_words"),
        source_text=user_message,
    )
    return compose_prompt("single_episode_script", data, mode=meta.get("mode"))

def _build_scene_asset_extract_prompt(user_message, word_count_wan, meta):
    data = _build_chat_prompt_data(
        user_message,
        word_count_wan,
        meta,
        source_text=user_message,
    )
    return compose_prompt("scene_asset_extract", data, mode=meta.get("mode"))


_HTTP_SESSION = _build_http_session()


def _extract_openai_compatible_text(resp_json: dict) -> str:
    """
    兼容 DeepSeek / zenmux.ai 这类 OpenAI 风格返回：
    {
      "choices": [
        {
          "message": {
            "content": "..."
          }
        }
      ]
    }
    """
    if not isinstance(resp_json, dict):
        raise ValueError("API响应不是有效 JSON 对象")

    choices = resp_json.get("choices")
    if not choices or not isinstance(choices, list):
        raise ValueError("API响应格式错误：未找到 choices 字段")

    first = choices[0] or {}
    message = first.get("message") or {}
    content = message.get("content")

    if content is None:
        raise ValueError("API响应格式错误：未找到 message.content")

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                txt = item.get("text")
                if txt:
                    parts.append(txt)
        content = "".join(parts)

    if not isinstance(content, str) or not content.strip():
        raise ValueError("API返回内容为空")

    return content.strip()


def _extract_standard_gemini_text(resp_json: dict) -> str:
    if not isinstance(resp_json, dict):
        raise ValueError("Gemini API响应不是有效 JSON 对象")

    candidates = resp_json.get("candidates")
    if not candidates or not isinstance(candidates, list):
        raise ValueError("Gemini API响应格式错误：未找到 candidates 字段")

    first = candidates[0] or {}
    content_obj = first.get("content") or {}
    parts = content_obj.get("parts") or []

    texts = []
    for part in parts:
        if isinstance(part, dict):
            txt = part.get("text")
            if txt:
                texts.append(txt)

    content = "".join(texts).strip()
    if not content:
        raise ValueError("Gemini API返回内容为空")

    return content


def _extract_ollama_text(resp_json: dict) -> str:
    if not isinstance(resp_json, dict):
        raise ValueError("Ollama API响应不是有效 JSON 对象")

    message = resp_json.get("message") or {}
    content = message.get("content")

    if not isinstance(content, str) or not content.strip():
        raise ValueError("Ollama API响应格式错误：未找到 message.content")

    return content.strip()


def _post_openai_compatible(
        host: str,
        api_key: str,
        model: str,
        messages: list,
        *,
        temperature: float = 0.8,
        max_tokens: int = 2000,
        request_name: str = "LLM"
) -> str:
    if not host:
        raise ValueError(f"{request_name} HOST 未配置")
    if not api_key:
        raise ValueError(f"{request_name} API_KEY 未配置")
    if not model:
        raise ValueError(f"{request_name} MODEL 未配置")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Connection": "close",
    }

    last_err = None

    for attempt in range(1, 4):
        try:
            resp = _HTTP_SESSION.post(
                host,
                headers=headers,
                json=payload,
                timeout=(10, 180),
            )

            try:
                data = resp.json()
            except Exception:
                data = None

            if resp.status_code == 200:
                if data is None:
                    raise ValueError(f"{request_name} 返回200，但不是合法JSON")
                return _extract_openai_compatible_text(data)

            detail = ""
            if isinstance(data, dict):
                detail = (
                        data.get("error", {}).get("message")
                        or data.get("message")
                        or data.get("detail")
                        or ""
                )
            if not detail:
                detail = resp.text[:500]

            if resp.status_code == 401:
                raise ValueError(f"{request_name} 鉴权失败，请检查 API Key：{detail}")
            if resp.status_code == 402:
                raise ValueError(f"{request_name} 余额不足：{detail}")
            if resp.status_code == 429:
                raise ValueError(f"{request_name} 请求过多或限流：{detail}")

            raise ValueError(f"{request_name} 调用失败，HTTP {resp.status_code}：{detail}")

        except ChunkedEncodingError as e:
            last_err = e
            if attempt < 3:
                time.sleep(attempt)
                continue
            raise ValueError(f"{request_name} 响应被中断（ChunkedEncodingError）：{e}")

        except RequestsConnectionError as e:
            last_err = e
            if attempt < 3:
                time.sleep(attempt)
                continue
            raise ValueError(f"{request_name} 连接失败：{e}")

        except RequestException as e:
            last_err = e
            if attempt < 3:
                time.sleep(attempt)
                continue
            raise ValueError(f"{request_name} 网络请求异常：{e}")

        except Exception as e:
            last_err = e
            raise

    raise ValueError(f"{request_name} 调用失败：{last_err}")


def _convert_messages_to_gemini_payload(messages):
    """
    把 OpenAI 风格 messages 转成 Gemini generateContent 所需格式：
    - system -> systemInstruction
    - user -> role=user
    - assistant -> role=model
    """
    system_texts = []
    contents = []

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue

        role = (msg.get("role") or "user").strip().lower()
        content = (msg.get("content") or "").strip()
        if not content:
            continue

        if role == "system":
            system_texts.append(content)
        elif role == "assistant":
            contents.append({
                "role": "model",
                "parts": [{"text": content}]
            })
        else:
            contents.append({
                "role": "user",
                "parts": [{"text": content}]
            })

    system_instruction = None
    if system_texts:
        system_instruction = {
            "parts": [{"text": "\n\n".join(system_texts)}]
        }

    # 如果只有 system，没有 user 内容，给一个兜底 user
    if not contents:
        contents = [{
            "role": "user",
            "parts": [{"text": "请根据系统指令执行。"}]
        }]

    return system_instruction, contents


def _build_gemini_generate_content_url(host: str, model: str) -> str:
    """
    兼容几种 GEMINI_HOST 写法：
    1. https://generativelanguage.googleapis.com/v1beta
    2. https://generativelanguage.googleapis.com/v1beta/
    3. https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
    4. 已经是完整 generateContent 地址
    """
    host = (host or "").strip()
    if not host:
        raise ValueError("Gemini HOST 未配置")

    if "{model}" in host:
        return host.format(model=model)

    if host.endswith(":generateContent"):
        return host

    if host.endswith("/"):
        host = host[:-1]

    # 如果只是 v1beta 根地址，则自动补全
    if host.endswith("/v1beta"):
        return f"{host}/models/{model}:generateContent"

    # 如果已经写到 models/xxx 但没带 generateContent
    if f"/models/{model}" in host and not host.endswith(":generateContent"):
        return f"{host}:generateContent"

    # 兜底：按 base url 处理
    return f"{host}/models/{model}:generateContent"


def _post_standard_gemini(
        host: str,
        api_key: str,
        model: str,
        messages: list,
        *,
        temperature: float = 0.8,
        max_tokens: int = 2000,
        request_name: str = "Gemini"
) -> str:
    """
    Gemini 官方 REST：models/{model}:generateContent
    """
    if not host:
        raise ValueError(f"{request_name} HOST 未配置")
    if not api_key:
        raise ValueError(f"{request_name} API_KEY 未配置")
    if not model:
        raise ValueError(f"{request_name} MODEL 未配置")

    url = _build_gemini_generate_content_url(host, model)
    system_instruction, contents = _convert_messages_to_gemini_payload(messages)

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens
        }
    }

    if system_instruction:
        payload["systemInstruction"] = system_instruction

    headers = {
        "Content-Type": "application/json",
        "Connection": "close",
    }

    last_err = None

    for attempt in range(1, 4):
        try:
            resp = _HTTP_SESSION.post(
                url,
                headers=headers,
                params={"key": api_key},
                json=payload,
                timeout=(10, 180),
            )

            try:
                data = resp.json()
            except Exception:
                data = None

            if resp.status_code == 200:
                if data is None:
                    raise ValueError(f"{request_name} 返回200，但不是合法JSON")
                return _extract_standard_gemini_text(data)

            detail = ""
            if isinstance(data, dict):
                detail = (
                    data.get("error", {}).get("message")
                    or data.get("message")
                    or data.get("detail")
                    or ""
                )
            if not detail:
                detail = resp.text[:500]

            if resp.status_code == 400:
                raise ValueError(f"{request_name} 请求参数错误：{detail}")
            if resp.status_code == 401:
                raise ValueError(f"{request_name} 鉴权失败，请检查 API Key：{detail}")
            if resp.status_code == 403:
                raise ValueError(f"{request_name} 权限不足或被拒绝：{detail}")
            if resp.status_code == 429:
                raise ValueError(f"{request_name} 请求过多或限流：{detail}")

            raise ValueError(f"{request_name} 调用失败，HTTP {resp.status_code}：{detail}")

        except ChunkedEncodingError as e:
            last_err = e
            if attempt < 3:
                time.sleep(attempt)
                continue
            raise ValueError(f"{request_name} 响应被中断（ChunkedEncodingError）：{e}")

        except RequestsConnectionError as e:
            last_err = e
            if attempt < 3:
                time.sleep(attempt)
                continue
            raise ValueError(f"{request_name} 连接失败：{e}")

        except RequestException as e:
            last_err = e
            if attempt < 3:
                time.sleep(attempt)
                continue
            raise ValueError(f"{request_name} 网络请求异常：{e}")

        except Exception:
            raise

    raise ValueError(f"{request_name} 调用失败：{last_err}")


def _post_ollama(
        host: str,
        model: str,
        messages: list,
        *,
        request_name: str = "Ollama"
) -> str:
    """
    Ollama /api/chat
    """
    if not host:
        raise ValueError(f"{request_name} HOST 未配置")
    if not model:
        raise ValueError(f"{request_name} MODEL 未配置")

    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }

    headers = {
        "Content-Type": "application/json",
        "Connection": "close",
    }

    last_err = None

    for attempt in range(1, 4):
        try:
            resp = _HTTP_SESSION.post(
                host,
                headers=headers,
                json=payload,
                timeout=(10, 600),  # 本地 32b 允许更久一点
            )

            try:
                data = resp.json()
            except Exception:
                data = None

            if resp.status_code == 200:
                if data is None:
                    raise ValueError(f"{request_name} 返回200，但不是合法JSON")
                return _extract_ollama_text(data)

            detail = ""
            if isinstance(data, dict):
                detail = data.get("error") or data.get("message") or ""
            if not detail:
                detail = resp.text[:500]

            raise ValueError(f"{request_name} 调用失败，HTTP {resp.status_code}：{detail}")

        except ChunkedEncodingError as e:
            last_err = e
            if attempt < 3:
                time.sleep(attempt)
                continue
            raise ValueError(f"{request_name} 响应被中断（ChunkedEncodingError）：{e}")

        except RequestsConnectionError as e:
            last_err = e
            if attempt < 3:
                time.sleep(attempt)
                continue
            raise ValueError(f"{request_name} 连接失败：{e}")

        except RequestException as e:
            last_err = e
            if attempt < 3:
                time.sleep(attempt)
                continue
            raise ValueError(f"{request_name} 网络请求异常：{e}")

        except Exception:
            raise

    raise ValueError(f"{request_name} 调用失败：{last_err}")


def _call_model(messages, current_api=None, temperature=0.7, max_tokens=8192):
    current_api = (current_api or API or '').strip().lower()

    if current_api == 'deepseek':
        return _clean_model_content(_post_openai_compatible(
            host=DEEPSEEK_HOST,
            api_key=DEEPSEEK_API_KEY,
            model=DEEPSEEK_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            request_name="DeepSeek",
        ))

    if current_api == 'gemini':
        if _looks_like_openai_compatible_host(GEMINI_HOST):
            return _clean_model_content(_post_openai_compatible(
                host=GEMINI_HOST,
                api_key=GEMINI_API_KEY,
                model=GEMINI_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                request_name="Gemini",
            ))

        return _clean_model_content(_post_standard_gemini(
            host=GEMINI_HOST,
            api_key=GEMINI_API_KEY,
            model=GEMINI_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            request_name="Gemini",
        ))

    if current_api == 'ollama':
        return _clean_model_content(_post_ollama(
            host=OLLAMA_HOST,
            model=OLLAMA_MODEL,
            messages=messages,
            request_name="Ollama",
        ))

    raise ValueError(f"不支持的模型：{current_api}")


def call_api(prompt):
    """生成内容"""
    current_api = session.get('selected_model', API)
    messages = _build_messages(
        '你是一个专业的剧本创作助手，擅长帮助作者完善剧本的各个方面。',
        prompt
    )
    return _call_model(messages, current_api, temperature=0.7, max_tokens=8192)

def _call_api_for_chat(prompt, selected_model=None):
    """
    专门给 Chat 流程使用的 LLM 调用函数。
    注意：不能直接调用你原来的 call_api()，因为它依赖 request/session，
    而这里的任务可能在后台线程里执行。
    """
    messages = _build_messages(
        "你是一个专业的剧本创作智能体，擅长总编剧拆解、人物塑造、剧情大纲设计与商业化短剧审核。",
        prompt
    )
    return _call_model(messages, selected_model or API, temperature=0.7, max_tokens=8192)

CHAT_TASK_STORE = {}
CHAT_TRACE_STORE = {}
CHAT_RESULT_STORE = {}
_CHAT_STORE_LOCK = threading.Lock()
_ALLOWED_CHAT_MODELS = {'deepseek', 'gemini', 'ollama'}

STAGE_UI_META = {
    "queued": {
        "step": "已创建任务",
        "running_title": "已收到你的需求",
        "done_title": "任务已创建",
        "default_running_message": "已收到你的需求，正在创建本次创作任务。",
        "default_done_message": "创作任务已创建，马上开始搭建人物和剧情。",
        "progress_running": 5,
        "progress_done": 8,
    },
    "character_bible": {
        "step": "人物设定",
        "running_title": "正在搭建人物关系",
        "done_title": "人物设定已完成",
        "default_running_message": "我先帮你把人物关系搭起来，先确定主角、对手和关键配角。",
        "default_done_message": "人物设定已完成，角色冲突已经建立。",
        "progress_running": 18,
        "progress_done": 30,
    },
    "plot_outline": {
        "step": "剧情大纲",
        "running_title": "正在搭建剧情骨架",
        "done_title": "剧情大纲已完成",
        "default_running_message": "现在开始搭剧情骨架，梳理故事主线、阶段推进和关键反转。",
        "default_done_message": "剧情大纲已完成，主线结构已经清晰。",
        "progress_running": 40,
        "progress_done": 55,
    },
    "review_report": {
        "step": "审核意见",
        "running_title": "正在检查节奏和逻辑",
        "done_title": "审核意见已完成",
        "default_running_message": "我在检查这个方案的节奏、逻辑和商业化潜力。",
        "default_done_message": "审核完成，已经整理出优化方向。",
        "progress_running": 68,
        "progress_done": 78,
    },
    "final_script": {
        "step": "最终稿",
        "running_title": "正在整合最终版本",
        "done_title": "最终稿主体已生成",
        "default_running_message": "正在整合前面的内容，生成最终版本。",
        "default_done_message": "最终稿主体已经生成，正在做最后整理。",
        "progress_running": 88,
        "progress_done": 95,
    },
    "done": {
        "step": "已完成",
        "running_title": "正在收尾",
        "done_title": "最终稿已完成",
        "default_running_message": "正在做最后收尾。",
        "default_done_message": "最终稿已完成，你现在可以查看完整内容。",
        "progress_running": 98,
        "progress_done": 100,
    },
    "failed": {
        "step": "生成失败",
        "running_title": "生成中断",
        "done_title": "生成失败",
        "default_running_message": "本次生成未能完成。",
        "default_done_message": "本次生成未能完成。",
        "progress_running": 0,
        "progress_done": 0,
    },
}


def _get_stage_ui(stage: str, status: str = "running") -> dict:
    meta = STAGE_UI_META.get(stage) or {
        "step": stage or "未知阶段",
        "running_title": f"正在处理 {stage or '任务'}",
        "done_title": f"{stage or '任务'} 已完成",
        "default_running_message": "",
        "default_done_message": "",
        "progress_running": 0,
        "progress_done": 0,
    }

    if status == "done":
        return {
            "step": meta["step"],
            "title": meta.get("done_title", meta["running_title"]),
            "message": meta.get("default_done_message", meta.get("default_running_message", "")),
            "progress": meta.get("progress_done", meta.get("progress_running", 0)),
        }

    if status == "failed":
        failed_meta = STAGE_UI_META["failed"]
        return {
            "step": failed_meta["step"],
            "title": failed_meta["done_title"],
            "message": failed_meta["default_done_message"],
            "progress": failed_meta["progress_done"],
        }

    return {
        "step": meta["step"],
        "title": meta.get("running_title", meta["step"]),
        "message": meta.get("default_running_message", ""),
        "progress": meta.get("progress_running", 0),
    }


def _build_trace_item(stage: str, *, status: str = "running", message: str = "", preview: str = "") -> dict:
    ui = _get_stage_ui(stage, status=status)
    return {
        "stage": stage,
        "step": ui["step"],
        "status": status,
        "title": ui["title"],
        "message": message or ui["message"],
        "preview": preview or "",
        "progress": ui["progress"],
        "time": _utc_now_iso(),
    }


def _update_task_stage(task_id: str, stage: str, *, status: str = "running", message: str = "", error: str = ""):
    ui = _get_stage_ui(stage, status=status)
    return _update_task_record(
        task_id,
        status=status,
        current_stage=stage,
        current_title=ui["title"],
        current_message=message or ui["message"],
        progress=ui["progress"],
        error=error or "",
    )


def _task_payload_view(task: dict) -> dict:
    stage = task.get("current_stage") or "queued"
    status = task.get("status") or "pending"

    if status == "done":
        ui = _get_stage_ui("done", status="done")
    elif status == "failed":
        ui = _get_stage_ui("failed", status="failed")
    else:
        ui = _get_stage_ui(stage, status="running")

    payload = {"task_id": task.get("task_id"), "project_id": task.get("project_id"), "status": status,
               "current_stage": stage, "current_title": task.get("current_title") or ui["title"],
               "current_message": task.get("current_message") or ui["message"],
               "progress": task.get("progress", ui["progress"]), "error": task.get("error", ""),
               "selected_model": task.get("selected_model"), "created_at": task.get("created_at"),
               "updated_at": task.get("updated_at"), "episode_count": int(task.get("episode_count") or 0),
               "generated_episode_count": int(task.get("generated_episode_count") or 0),
               "current_episode_no": int(task.get("current_episode_no") or 0)}

    return payload


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _safe_preview(text, limit=120):
    text = (text or '').strip()
    text = re.sub(r'\s+', ' ', text)
    if len(text) <= limit:
        return text
    return text[:limit] + '...'


def _normalize_selected_model(model_name):
    model_name = (model_name or '').strip().lower()
    if not model_name:
        model_name = (session.get('selected_model') or API or 'deepseek').strip().lower()
    if model_name not in _ALLOWED_CHAT_MODELS:
        raise ValueError(f'不支持的模型：{model_name}')
    return model_name


def _make_default_title(user_message):
    first_line = (user_message or '').strip().splitlines()[0] if (user_message or '').strip() else '未命名项目'
    first_line = re.sub(r'\s+', ' ', first_line).strip()
    if not first_line:
        first_line = '未命名项目'
    if len(first_line) > 30:
        first_line = first_line[:30].rstrip() + '...'
    return first_line


def _task_snapshot(task_id):
    with _CHAT_STORE_LOCK:
        task = CHAT_TASK_STORE.get(task_id)
        if not task:
            return None
        return dict(task)


def _create_task_record(task_id, project_id, selected_model, user_id, user_message, meta=None):
    record = {
        'task_id': task_id,
        'project_id': project_id,
        'user_id': user_id,
        'selected_model': selected_model,
        'status': 'pending',
        'current_stage': 'queued',
        'error': '',
        'user_message': user_message,
        'meta': meta or {},
        'created_at': _utc_now_iso(),
        'updated_at': _utc_now_iso(),
    }
    with _CHAT_STORE_LOCK:
        CHAT_TASK_STORE[task_id] = record
    return record


def _update_task_record(task_id, **kwargs):
    with _CHAT_STORE_LOCK:
        task = CHAT_TASK_STORE.get(task_id)
        if not task:
            return None
        task.update(kwargs)
        task['updated_at'] = _utc_now_iso()
        return dict(task)


def _append_trace(project_id, stage, message, *, status="done", preview=""):
    with _CHAT_STORE_LOCK:
        trace = CHAT_TRACE_STORE.setdefault(project_id, [])
        ui = _get_stage_ui(stage if stage in STAGE_UI_META else "done", status="done" if status == "done" else "running")
        trace.append({
            "stage": stage,
            "step": ui["step"],
            "title": ui["title"] if status == "done" else STAGE_UI_META.get(stage, {}).get("running_title", stage),
            "message": message,
            "status": status,
            "preview": preview or "",
            "time": _utc_now_iso(),
        })


def _set_project_result(
    project_id,
    *,
    final_script=None,
    final_review=None,
    final_asset_text=None,
    character_bible=None,
    plot_outline=None,
    review_report=None,
):
    with _CHAT_STORE_LOCK:
        store = CHAT_RESULT_STORE.setdefault(project_id, {})
        if final_script is not None:
            store["final_script"] = final_script
        if final_review is not None:
            store["final_review"] = final_review
        if final_asset_text is not None:
            store["final_asset_text"] = final_asset_text
        if character_bible is not None:
            store["character_bible"] = character_bible
        if plot_outline is not None:
            store["plot_outline"] = plot_outline
        if review_report is not None:
            store["review_report"] = review_report
        store["updated_at"] = _utc_now_iso()
        return dict(store)


def _get_project_result(project_id):
    with _CHAT_STORE_LOCK:
        return dict(CHAT_RESULT_STORE.get(project_id) or {})


def _load_project_meta_payload(script: ScriptModel) -> dict:
    raw = (script.knowledge or "").strip()
    if not raw:
        return {}

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 兼容老数据：旧版 knowledge 可能只是纯文本
    return {
        "final_review": raw
    }


def _save_project_meta_payload(
    script: ScriptModel,
    *,
    review_report=None,
    final_review=None,
):
    payload = _load_project_meta_payload(script)

    if review_report is not None:
        payload["review_report"] = review_report or ""

    if final_review is not None:
        payload["final_review"] = final_review or ""

    script.knowledge = json.dumps(payload, ensure_ascii=False)


def _ensure_project_for_user(project_id, user_id, user_message, meta=None):
    meta = meta or {}
    word_count_wan = meta.get('word_count_wan') or 2
    try:
        word_count_wan = float(word_count_wan)
    except Exception:
        word_count_wan = 2

    if project_id:
        script = ScriptModel.query.get(project_id)
        if not script:
            raise ValueError('指定的 project_id 不存在')
        if script.user_id != user_id:
            raise ValueError('您没有权限访问该项目')
        if not script.title:
            script.title = _make_default_title(user_message)
        if not script.background:
            script.background = user_message or ''
        if not script.word_count:
            script.word_count = int(word_count_wan * 10000)
        db.session.commit()
        return script

    script = ScriptModel(
        title=_make_default_title(user_message),
        content='',
        background=user_message or '',
        characters='',
        relationships='',
        knowledge='',
        style='',
        write_style='chat_mvp',
        outline='',
        word_count=int(word_count_wan * 10000),
        style_type='2d_realistic',
        has_branching=False,
        mind_map='',
        genre='AI生成',
        user_id=user_id,
    )
    db.session.add(script)
    db.session.commit()
    return script


def _save_project_artifacts(
    project_id,
    *,
    user_message,
    final_script=None,
    final_review=None,
    final_asset_text=None,
    character_bible=None,
    plot_outline=None,
    review_report=None,
):
    _save_final_artifacts(
        project_id,
        user_message=user_message,
        final_script=final_script,
        final_review=final_review,
        final_asset_text=final_asset_text,
        character_bible=character_bible,
        plot_outline=plot_outline,
        review_report=review_report,
    )


def _save_partial_artifacts(
    project_id,
    *,
    user_message,
    final_script=None,
    final_review=None,
    final_asset_text=None,
    character_bible=None,
    plot_outline=None,
    review_report=None,
):
    script = ScriptModel.query.get(project_id)
    if script:
        if final_script is not None and str(final_script).strip():
            script.content = str(final_script).strip()
        if character_bible is not None:
            script.characters = character_bible or ""
        if plot_outline is not None:
            script.outline = plot_outline or ""
        if final_review is not None or review_report is not None:
            _save_project_meta_payload(
                script,
                review_report=review_report,
                final_review=final_review,
            )
        db.session.commit()

    _set_project_result(
        project_id,
        final_script=final_script,
        final_review=final_review,
        final_asset_text=final_asset_text,
        character_bible=character_bible,
        plot_outline=plot_outline,
        review_report=review_report,
    )


def _save_final_artifacts(
    project_id,
    *,
    user_message,
    final_script=None,
    final_review=None,
    final_asset_text=None,
    character_bible=None,
    plot_outline=None,
    review_report=None,
):
    script = ScriptModel.query.get(project_id)
    if script:
        # 约定：script.content 只保存正文剧本
        if final_script is not None:
            script.content = (final_script or "").strip()
        if character_bible is not None:
            script.characters = character_bible or ""
        if plot_outline is not None:
            script.outline = plot_outline or ""
        if final_review is not None:
            script.knowledge = final_review or ""
        elif review_report is not None:
            script.knowledge = review_report or ""
        db.session.commit()

    _set_project_result(
        project_id,
        final_script=final_script,
        final_review=final_review,
        final_asset_text=final_asset_text,
        character_bible=character_bible,
        plot_outline=plot_outline,
        review_report=review_report,
    )


def _build_character_prompt(user_message, word_count_wan, meta):
    data = _build_chat_prompt_data(
        user_message,
        word_count_wan,
        meta,
        source_text=user_message,
    )
    return compose_prompt("characters", data, mode=meta.get("mode"))


def _build_outline_prompt(user_message, word_count_wan, character_bible, meta):
    prompt_key = "episode_plan" if meta.get("output_granularity") in {"episode_plan", "multi_episode_script"} else "outline"
    data = _build_chat_prompt_data(
        user_message,
        word_count_wan,
        meta,
        history=character_bible,
        source_text=user_message,
    )
    return compose_prompt(prompt_key, data, mode=meta.get("mode"))


def _build_review_prompt(user_message, character_bible, plot_outline, meta):
    data = _build_chat_prompt_data(
        user_message,
        meta["word_count_wan"],
        meta,
        history=character_bible,
        content=plot_outline,
    )
    return compose_prompt("review_report", data, mode=meta.get("mode"))


def _build_final_review_prompt(
    user_message,
    word_count_wan,
    character_bible,
    plot_outline,
    review_report,
    meta,
):
    data = _build_chat_prompt_data(
        user_message,
        word_count_wan,
        meta,
        history=character_bible,
        content=plot_outline,
        review_report=review_report,
        source_text=user_message,
    )
    return compose_prompt("final_rewrite", data, mode=meta.get("mode"))


def _merge_episode_scripts(episode_texts):
    cleaned = []
    for text in episode_texts or []:
        t = (text or "").strip()
        if t:
            cleaned.append(t)
    return "\n\n".join(cleaned).strip()


def _resolve_episode_count(meta, full_episode_plan_text):
    try:
        count = int((meta or {}).get("episode_count") or 0)
        if count > 0:
            return count
    except Exception:
        pass

    nums = re.findall(r"第\s*(\d+)\s*集", full_episode_plan_text or "")
    if nums:
        try:
            return max(int(x) for x in nums)
        except Exception:
            pass

    return 10


def _extract_episode_plan_slice(full_plan_text, episode_no):
    text = full_plan_text or ""
    if not text.strip():
        return ""

    pattern = rf"(第\s*{episode_no}\s*集[\s\S]*?)(?=第\s*{episode_no + 1}\s*集|$)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()

    pattern2 = rf"(第\s*{episode_no}\s*集[:：]?[\s\S]*?)(?=第\s*{episode_no + 1}\s*集|$)"
    match2 = re.search(pattern2, text, flags=re.IGNORECASE)
    if match2:
        return match2.group(1).strip()

    return ""


def _get_episode_output_dir(project_id):
    base_dir = os.path.join(
        current_app.instance_path,
        "chat_episode_exports",
        f"project_{project_id}",
    )
    os.makedirs(base_dir, exist_ok=True)
    return base_dir


def _save_episode_to_local(project_id, episode_no, episode_text):
    output_dir = _get_episode_output_dir(project_id)
    file_path = os.path.join(output_dir, f"Episode-{episode_no:02d}.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write((episode_text or "").strip())
    return file_path


@api.route('/model/current', methods=['GET'])
@login_required
def get_current_model():
    try:
        selected_model = (session.get('selected_model') or API or 'deepseek').strip().lower()
        if selected_model not in _ALLOWED_CHAT_MODELS:
            selected_model = 'deepseek'
        return jsonify({
            'success': True,
            'selected_model': selected_model,
            'available_models': sorted(_ALLOWED_CHAT_MODELS),
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@api.route('/model/select', methods=['POST'])
@login_required
def select_model():
    try:
        data = request.get_json(silent=True) or {}
        selected_model = (data.get('model') or '').strip().lower()
        if selected_model not in _ALLOWED_CHAT_MODELS:
            return jsonify({
                'success': False,
                'message': f'不支持的模型：{selected_model}',
                'available_models': sorted(_ALLOWED_CHAT_MODELS),
            }), 400

        session['selected_model'] = selected_model
        return jsonify({
            'success': True,
            'selected_model': selected_model,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@api.route('/chat/send', methods=['POST'])
@login_required
def chat_send():
    try:
        data = request.get_json(silent=True) or {}
        user_message = (data.get('message') or '').strip()
        if not user_message:
            return jsonify({'success': False, 'message': 'message 不能为空'}), 400

        meta = _normalize_chat_meta(data.get('meta') or {})
        project_id = data.get('project_id')
        selected_model = _normalize_selected_model(data.get('model') or session.get('selected_model') or API)

        script = _ensure_project_for_user(
            project_id=project_id,
            user_id=current_user.id,
            user_message=user_message,
            meta=meta,
        )

        project_id = script.id
        task_id = uuid.uuid4().hex

        _create_task_record(
            task_id=task_id,
            project_id=project_id,
            selected_model=selected_model,
            user_id=current_user.id,
            user_message=user_message,
            meta=meta,
        )

        _update_task_record(
            task_id,
            status='pending',
            current_stage='queued',
            current_title='已收到你的需求',
            current_message='已收到你的需求，正在创建本次创作任务。',
            progress=5,
            error='',
        )

        _append_trace(
            project_id,
            'queued',
            '已收到你的需求，正在创建本次创作任务。',
            status='done',
        )

        app = current_app._get_current_object()
        worker = threading.Thread(
            target=_run_chat_generation,
            args=(app, task_id, project_id, current_user.id, user_message, meta, selected_model),
            daemon=True,
        )
        worker.start()

        return jsonify({
            'success': True,
            'task_id': task_id,
            'project_id': project_id,
            'status': 'pending',
            'current_stage': 'queued',
            'current_title': '已收到你的需求',
            'current_message': '已收到你的需求，正在创建本次创作任务。',
            'progress': 5,
            'selected_model': selected_model,
        })
    except Exception as e:
        logging.exception('创建聊天任务失败')
        return jsonify({'success': False, 'message': str(e)}), 500


@api.route('/chat/task/<task_id>', methods=['GET'])
@login_required
def get_chat_task(task_id):
    task = _task_snapshot(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    if task.get('user_id') != current_user.id:
        return jsonify({'success': False, 'message': '您没有权限访问该任务'}), 403

    payload = _task_payload_view(task)
    payload['success'] = True
    return jsonify(payload)


@api.route('/chat/project/<int:project_id>/artifacts', methods=['GET'])
@login_required
def get_project_artifacts(project_id):
    script = ScriptModel.query.get_or_404(project_id)
    if script.user_id != current_user.id:
        return jsonify({'success': False, 'message': '您没有权限访问该项目'}), 403

    result = _get_project_result(project_id)
    meta_payload = _load_project_meta_payload(script)

    script_text = (result.get("final_script", "") if result else "") or (script.content or "")
    final_review = (result.get("final_review", "") if result else "") or meta_payload.get("final_review", "")
    character_bible = (result.get("character_bible", "") if result else "") or (script.characters or "")
    plot_outline = (result.get("plot_outline", "") if result else "") or (script.outline or "")
    review_report = (result.get("review_report", "") if result else "") or meta_payload.get("review_report", "")
    final_asset_text = (result.get("final_asset_text", "") if result else "")

    return jsonify({
        'success': True,
        'project_id': project_id,
        'script_text': script_text,
        'final_review': final_review,
        'final_script': script_text,
        'character_bible': character_bible,
        'plot_outline': plot_outline,
        'review_report': review_report,
        'final_asset_text': final_asset_text,
    })


@api.route('/chat/project/<int:project_id>/trace', methods=['GET'])
@login_required
def get_project_trace(project_id):
    script = ScriptModel.query.get_or_404(project_id)
    if script.user_id != current_user.id:
        return jsonify({'success': False, 'message': '您没有权限访问该项目'}), 403

    with _CHAT_STORE_LOCK:
        trace = list(CHAT_TRACE_STORE.get(project_id) or [])

    return jsonify({
        'success': True,
        'project_id': project_id,
        'trace': trace,
    })


def _run_multi_episode_script_generation(
    task_id,
    project_id,
    user_message,
    word_count_wan,
    character_bible,
    full_episode_plan_text,
    review_report,
    meta,
    selected_model,
):
    total = _resolve_episode_count(meta, full_episode_plan_text)

    try:
        total_words = max(1000, int(float(word_count_wan) * 10000))
    except Exception:
        total_words = 20000

    episode_target_words = max(700, round(total_words / max(total, 1)))
    episode_texts = []

    for ep in range(1, total + 1):
        current_episode_plan = _extract_episode_plan_slice(full_episode_plan_text, ep)

        ep_meta = dict(meta or {})
        ep_meta["output_granularity"] = "single_episode_script"
        ep_meta["current_episode_no"] = ep
        ep_meta["generated_episode_count"] = len(episode_texts)
        ep_meta["episode_count"] = total
        ep_meta["episode_target_words"] = episode_target_words

        _update_task_record(
            task_id,
            status="running",
            current_stage="final_script",
            current_title=f"正在生成第 {ep} 集 / 共 {total} 集",
            current_message=f"当前已生成 {len(episode_texts)} 集，共 {total} 集",
            progress=55 + int(40 * (len(episode_texts) / max(total, 1))),
            current_episode_no=ep,
            generated_episode_count=len(episode_texts),
            episode_count=total,
        )

        prompt = _build_single_episode_script_prompt(
            user_message=user_message,
            word_count_wan=word_count_wan,
            character_bible=character_bible,
            current_episode_plan=current_episode_plan,
            current_episode_no=ep,
            meta=ep_meta,
        )

        episode_text = _call_api_for_chat(
            prompt,
            selected_model=selected_model,
        )

        episode_texts.append(episode_text)

        save_path = _save_episode_to_local(project_id, ep, episode_text)
        combined_text = _merge_episode_scripts(episode_texts)

        _save_partial_artifacts(
            project_id,
            user_message=user_message,
            final_script=combined_text,
            character_bible=character_bible,
            plot_outline=full_episode_plan_text,
            review_report=review_report,
        )

        _append_trace(
            project_id,
            "final_script",
            f"第 {ep} 集已生成完成，并已自动保存：{os.path.basename(save_path)}",
            status="done",
            preview=_safe_preview(episode_text, 180),
        )

        _update_task_record(
            task_id,
            status="running",
            current_stage="final_script",
            current_title=f"第 {ep} 集已完成",
            current_message=f"当前已生成 {ep} 集，共 {total} 集",
            progress=55 + int(40 * (ep / max(total, 1))),
            current_episode_no=ep,
            generated_episode_count=ep,
            episode_count=total,
        )

    final_script = _merge_episode_scripts(episode_texts)

    _save_final_artifacts(
        project_id,
        user_message=user_message,
        final_script=final_script,
        character_bible=character_bible,
        plot_outline=full_episode_plan_text,
        review_report=review_report,
    )

    final_combined_path = os.path.join(
        _get_episode_output_dir(project_id),
        "All-Episodes.txt",
    )
    with open(final_combined_path, "w", encoding="utf-8") as f:
        f.write(final_script)

    _append_trace(
        project_id,
        "done",
        f"多集剧本已完成，合并文件已保存：{os.path.basename(final_combined_path)}",
        status="done",
    )

    _update_task_record(
        task_id,
        status="done",
        current_stage="done",
        current_title="多集剧本已完成",
        current_message=f"已连续生成完成，共 {total} 集",
        progress=100,
        current_episode_no=total,
        generated_episode_count=total,
        episode_count=total,
    )

    return final_script


def _run_chat_generation(app, task_id, project_id, user_id, user_message, meta, selected_model):
    stage_being_processed = "queued"

    with app.app_context():
        try:
            word_count_wan = meta.get("word_count_wan", 2)
            try:
                word_count_wan = float(word_count_wan)
            except Exception:
                word_count_wan = 2.0

            granularity = meta.get("output_granularity", "outline")

            # 1) 人物设定
            stage_being_processed = "character_bible"
            _update_task_stage(
                task_id,
                "character_bible",
                status="running",
                message="我先帮你把人物关系搭起来，先确定主角、对手和关键配角。",
            )
            _append_trace(
                project_id,
                "character_bible",
                "我先帮你把人物关系搭起来，先确定主角、对手和关键配角。",
                status="running",
            )

            character_bible = _call_api_for_chat(
                _build_character_prompt(user_message, word_count_wan, meta),
                selected_model=selected_model,
            )
            _save_partial_artifacts(
                project_id,
                user_message=user_message,
                character_bible=character_bible,
            )
            _append_trace(
                project_id,
                "character_bible",
                "人物设定已完成，角色冲突已经建立。",
                status="done",
                preview=_safe_preview(character_bible, 180),
            )

            # 2) 总纲 / 分集计划
            stage_being_processed = "plot_outline"
            _update_task_stage(
                task_id,
                "plot_outline",
                status="running",
                message="现在开始搭剧情骨架，梳理故事主线、阶段推进和关键反转。",
            )
            _append_trace(
                project_id,
                "plot_outline",
                "现在开始搭剧情骨架，梳理故事主线、阶段推进和关键反转。",
                status="running",
            )

            plot_outline = _call_api_for_chat(
                _build_outline_prompt(user_message, word_count_wan, character_bible, meta),
                selected_model=selected_model,
            )
            _save_partial_artifacts(
                project_id,
                user_message=user_message,
                plot_outline=plot_outline,
            )
            _append_trace(
                project_id,
                "plot_outline",
                "剧情结构已完成。",
                status="done",
                preview=_safe_preview(plot_outline, 180),
            )

            # 3) 审核意见
            stage_being_processed = "review_report"
            _update_task_stage(
                task_id,
                "review_report",
                status="running",
                message="我在检查这个方案的结构、节奏和格式合规性。",
            )
            _append_trace(
                project_id,
                "review_report",
                "我在检查这个方案的结构、节奏和格式合规性。",
                status="running",
            )

            review_report = _call_api_for_chat(
                _build_review_prompt(user_message, character_bible, plot_outline, meta),
                selected_model=selected_model,
            )
            _save_partial_artifacts(
                project_id,
                user_message=user_message,
                review_report=review_report,
            )
            _append_trace(
                project_id,
                "review_report",
                "审核完成，已经整理出优化方向。",
                status="done",
                preview=_safe_preview(review_report, 180),
            )

            # 4) 按输出粒度决定最终交付物
            stage_being_processed = "final_script"
            _update_task_stage(
                task_id,
                "final_script",
                status="running",
                message="正在整合前面的内容，生成最终交付物。",
            )
            _append_trace(
                project_id,
                "final_script",
                "正在整合前面的内容，生成最终交付物。",
                status="running",
            )

            if granularity == "multi_episode_script":
                _run_multi_episode_script_generation(
                    task_id=task_id,
                    project_id=project_id,
                    user_message=user_message,
                    word_count_wan=word_count_wan,
                    character_bible=character_bible,
                    full_episode_plan_text=plot_outline,
                    review_report=review_report,
                    meta=meta,
                    selected_model=selected_model,
                )
                return

            if granularity == "single_episode_script":
                current_episode_no = int(meta.get("current_episode_no") or 1)
                total_episode_count = _resolve_episode_count(meta, plot_outline)
                current_episode_no = max(1, min(current_episode_no, total_episode_count))
                current_episode_plan = _extract_episode_plan_slice(plot_outline, current_episode_no)
                final_script = _call_api_for_chat(
                    _build_single_episode_script_prompt(
                        user_message=user_message,
                        word_count_wan=word_count_wan,
                        character_bible=character_bible,
                        current_episode_plan=current_episode_plan,
                        current_episode_no=current_episode_no,
                        meta=meta,
                    ),
                    selected_model=selected_model,
                )

                _save_final_artifacts(
                    project_id,
                    user_message=user_message,
                    final_script=final_script,
                    character_bible=character_bible,
                    plot_outline=plot_outline,
                    review_report=review_report,
                )
                _append_trace(
                    project_id,
                    "final_script",
                    "单集剧本已完成。",
                    status="done",
                    preview=_safe_preview(final_script, 180),
                )
                _update_task_stage(
                    task_id,
                    "done",
                    status="done",
                    message="单集剧本已完成，你现在可以查看完整内容。",
                )
                _append_trace(
                    project_id,
                    "done",
                    "单集剧本已完成，你现在可以查看完整内容。",
                    status="done",
                )
                return

            if granularity == "scene_asset_extract":
                final_assets = _call_api_for_chat(
                    _build_scene_asset_extract_prompt(user_message, word_count_wan, meta),
                    selected_model=selected_model,
                )

                _save_partial_artifacts(
                    project_id,
                    user_message=user_message,
                    final_asset_text=final_assets,
                    character_bible=character_bible,
                    plot_outline=plot_outline,
                    review_report=review_report,
                )

                _append_trace(
                    project_id,
                    "final_script",
                    "场景资产已完成。",
                    status="done",
                    preview=_safe_preview(final_assets, 180),
                )
                _update_task_stage(
                    task_id,
                    "done",
                    status="done",
                    message="场景资产已完成，你现在可以查看完整内容。",
                )
                _append_trace(
                    project_id,
                    "done",
                    "场景资产已完成，你现在可以查看完整内容。",
                    status="done",
                )
                return

            # outline / episode_plan 统一输出“总编剧定稿”
            final_review = _call_api_for_chat(
                _build_final_review_prompt(
                    user_message,
                    word_count_wan,
                    character_bible,
                    plot_outline,
                    review_report,
                    meta,
                ),
                selected_model=selected_model,
            )

            _save_final_artifacts(
                project_id,
                user_message=user_message,
                final_script="",
                final_review=final_review,
                character_bible=character_bible,
                plot_outline=plot_outline,
                review_report=review_report,
            )
            _append_trace(
                project_id,
                "final_script",
                "总编剧定稿已完成。",
                status="done",
                preview=_safe_preview(final_review, 180),
            )
            _update_task_stage(
                task_id,
                "done",
                status="done",
                message="总编剧定稿已完成，你现在可以查看完整内容。",
            )
            _append_trace(
                project_id,
                "done",
                "总编剧定稿已完成，你现在可以查看完整内容。",
                status="done",
            )
            return

        except Exception as e:
            logging.exception("Chat 任务执行失败 task_id=%s project_id=%s", task_id, project_id)
            _update_task_record(
                task_id,
                status="failed",
                current_stage=stage_being_processed,
                current_title="本次生成未完成",
                current_message=str(e),
                error=str(e),
            )
            _append_trace(
                project_id,
                stage_being_processed,
                f"这一阶段未能完成：{str(e)}",
                status="failed",
            )