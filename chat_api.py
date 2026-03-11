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
from requests.adapters import HTTPAdapter
from requests.exceptions import ChunkedEncodingError, ConnectionError as RequestsConnectionError, RequestException
from urllib3.util.retry import Retry
from datetime import datetime, timezone
from flask import current_app

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