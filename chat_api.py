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

CHAT_TASK_STORE = {}
CHAT_TRACE_STORE = {}
CHAT_RESULT_STORE = {}
_CHAT_STORE_LOCK = threading.Lock()
_ALLOWED_CHAT_MODELS = {'deepseek', 'gemini', 'ollama'}


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


def _append_trace(project_id, stage, summary):
    item = {
        'stage': stage,
        'time': _utc_now_iso(),
        'summary': summary,
    }
    with _CHAT_STORE_LOCK:
        CHAT_TRACE_STORE.setdefault(project_id, []).append(item)
    return item


def _set_project_result(project_id, *, final_script='', character_bible='', plot_outline='', review_report=''):
    with _CHAT_STORE_LOCK:
        CHAT_RESULT_STORE[project_id] = {
            'final_script': final_script or '',
            'character_bible': character_bible or '',
            'plot_outline': plot_outline or '',
            'review_report': review_report or '',
            'updated_at': _utc_now_iso(),
        }


def _get_project_result(project_id):
    with _CHAT_STORE_LOCK:
        return dict(CHAT_RESULT_STORE.get(project_id) or {})


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


def _save_project_artifacts(project_id, *, user_message, final_script, character_bible, plot_outline, review_report):
    script = ScriptModel.query.get(project_id)
    if not script:
        raise ValueError(f'项目不存在：{project_id}')

    script.background = user_message or script.background or ''
    script.content = final_script or ''
    script.characters = character_bible or ''
    script.outline = plot_outline or ''
    script.knowledge = review_report or ''
    script.updated_at = datetime.utcnow()
    db.session.commit()

    _set_project_result(
        project_id,
        final_script=final_script,
        character_bible=character_bible,
        plot_outline=plot_outline,
        review_report=review_report,
    )


def _build_character_prompt(user_message, word_count_wan):
    return f'''你现在是“人物编剧”。
请根据用户需求，输出一份完整的人物设定文档。

要求：
1. 至少包含：主角、核心对手、关键配角。
2. 每个角色至少写：姓名、身份、年龄层、性格关键词、表层目标、真实欲望、主要矛盾、与主角关系、人物弧光。
3. 先给“角色总览”，再展开重点人物。
4. 输出必须是中文，结构清晰，适合后续继续生成剧情。

目标字数：约 {word_count_wan} 万字项目
用户需求：
{user_message}'''


def _build_outline_prompt(user_message, word_count_wan, character_bible):
    return f'''你现在是“剧情编剧”。
请基于用户需求和人物设定，输出一份剧情大纲。

要求：
1. 先给一句话卖点。
2. 再给故事总纲。
3. 再给“三幕式/阶段式”推进。
4. 再给关键反转、高潮、结尾落点。
5. 再给可直接进入分章写作的章节/集数规划。
6. 输出必须是中文，结构清晰。

目标字数：约 {word_count_wan} 万字项目
用户需求：
{user_message}

人物设定：
{character_bible}'''


def _build_review_prompt(user_message, character_bible, plot_outline):
    return f'''你现在是“审核编剧”。
请审查下面这套项目方案是否适合商业化网文/短剧开发。

请输出：
1. 总体判断
2. 亮点
3. 风险点
4. 逻辑漏洞
5. 人物问题
6. 节奏问题
7. 修改建议

用户需求：
{user_message}

人物设定：
{character_bible}

剧情大纲：
{plot_outline}'''


def _build_final_script_prompt(user_message, word_count_wan, character_bible, plot_outline, review_report):
    return f'''你现在是“总编剧”。
请综合用户需求、人物设定、剧情大纲和审核意见，输出最终创作稿。

要求：
1. 先给项目定位与题眼。
2. 再给最终版故事总纲。
3. 再给详细阶段推进。
4. 再给主要人物在最终稿中的关系和冲突安排。
5. 最后给一个高完成度的开篇样章/样集正文。
6. 输出必须是中文，可读性强，避免空泛口号。

目标字数：约 {word_count_wan} 万字项目
用户需求：
{user_message}

人物设定：
{character_bible}

剧情大纲：
{plot_outline}

审核意见：
{review_report}'''


def _run_chat_generation(app, task_id, project_id, user_id, user_message, meta, selected_model):
    with app.app_context():
        try:
            word_count_wan = meta.get('word_count_wan', 2)
            try:
                word_count_wan = float(word_count_wan)
            except Exception:
                word_count_wan = 2

            _update_task_record(task_id, status='running', current_stage='character_bible')
            _append_trace(project_id, 'character_bible', '开始生成人物设定')
            character_bible = _call_api_for_chat(
                _build_character_prompt(user_message, word_count_wan),
                selected_model=selected_model,
            )
            _append_trace(project_id, 'character_bible', _safe_preview(character_bible))

            _update_task_record(task_id, status='running', current_stage='plot_outline')
            _append_trace(project_id, 'plot_outline', '开始生成剧情大纲')
            plot_outline = _call_api_for_chat(
                _build_outline_prompt(user_message, word_count_wan, character_bible),
                selected_model=selected_model,
            )
            _append_trace(project_id, 'plot_outline', _safe_preview(plot_outline))

            _update_task_record(task_id, status='running', current_stage='review_report')
            _append_trace(project_id, 'review_report', '开始生成审核报告')
            review_report = _call_api_for_chat(
                _build_review_prompt(user_message, character_bible, plot_outline),
                selected_model=selected_model,
            )
            _append_trace(project_id, 'review_report', _safe_preview(review_report))

            _update_task_record(task_id, status='running', current_stage='final_script')
            _append_trace(project_id, 'final_script', '开始生成最终稿')
            final_script = _call_api_for_chat(
                _build_final_script_prompt(user_message, word_count_wan, character_bible, plot_outline, review_report),
                selected_model=selected_model,
            )
            _append_trace(project_id, 'final_script', _safe_preview(final_script))

            _save_project_artifacts(
                project_id,
                user_message=user_message,
                final_script=final_script,
                character_bible=character_bible,
                plot_outline=plot_outline,
                review_report=review_report,
            )

            _update_task_record(task_id, status='done', current_stage='done', error='')
            _append_trace(project_id, 'done', '任务完成')

        except Exception as e:
            logging.exception('Chat 任务执行失败 task_id=%s project_id=%s', task_id, project_id)
            _update_task_record(task_id, status='failed', current_stage='failed', error=str(e))
            _append_trace(project_id, 'failed', f'任务失败：{str(e)}')


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

        meta = data.get('meta') or {}
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
        _append_trace(project_id, 'queued', f'任务已创建，使用模型：{selected_model}')

        app = current_app._get_current_object()
        worker = threading.Thread(
            target=_run_chat_generation,
            args=(app, task_id, project_id, current_user.id, user_message, meta, selected_model),
            daemon=True,
        )
        worker.start()

        _update_task_record(task_id, status='pending', current_stage='queued')

        return jsonify({
            'success': True,
            'task_id': task_id,
            'project_id': project_id,
            'status': 'pending',
            'current_stage': 'queued',
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

    return jsonify({
        'success': True,
        'task_id': task.get('task_id'),
        'project_id': task.get('project_id'),
        'status': task.get('status'),
        'current_stage': task.get('current_stage'),
        'error': task.get('error', ''),
        'selected_model': task.get('selected_model'),
        'created_at': task.get('created_at'),
        'updated_at': task.get('updated_at'),
    })


@api.route('/chat/project/<int:project_id>/artifacts', methods=['GET'])
@login_required
def get_project_artifacts(project_id):
    script = ScriptModel.query.get_or_404(project_id)
    if script.user_id != current_user.id:
        return jsonify({'success': False, 'message': '您没有权限访问该项目'}), 403

    result = _get_project_result(project_id)
    if not result:
        result = {
            'final_script': script.content or '',
            'character_bible': script.characters or '',
            'plot_outline': script.outline or '',
            'review_report': script.knowledge or '',
        }

    return jsonify({
        'success': True,
        'project_id': project_id,
        'final_script': result.get('final_script', ''),
        'character_bible': result.get('character_bible', ''),
        'plot_outline': result.get('plot_outline', ''),
        'review_report': result.get('review_report', ''),
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