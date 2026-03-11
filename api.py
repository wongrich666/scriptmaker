# ============================================================
# Chat MVP API（问题2）作用与操作说明
# ============================================================
# 1. 这版是 MVP，不是最终版
# 2. task / trace 暂时不落库
# 3. 主要目的是先把聊天入口打通
# 4. 后续可以把 CHAT_TASK_STORE 改成数据库表：
#    conversation_session / generation_task / agent_trace 等
# 5. 后续也可以把“人物 / 剧情 / 审核”从 api.py 再拆到
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

def call_api(prompt):
    """生成内容"""
    # 从session获取当前使用的模型，如果没有则使用默认的API
    current_api = session.get('selected_model', API)
    
    # 构建消息
    messages = [
        {
            'role': 'system',
            'content': '你是一个专业的剧本创作助手，擅长帮助作者完善剧本的各个方面。'
        },
        {
            'role': 'user',
            'content': prompt
        }
    ]
    # print(prompt)
    if current_api == 'deepseek':
        response = requests.post(
            DEEPSEEK_HOST,
            headers={
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': DEEPSEEK_MODEL,
                'messages': messages,
                'temperature': 0.7,
                'max_tokens': 8192,
                'stream': False
            },
            timeout=300
        )
    elif current_api == 'gemini':
        response = requests.post(
            GEMINI_HOST,
            headers={
                'Authorization': f'Bearer {GEMINI_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': GEMINI_MODEL,
                'messages': messages,
                'temperature': 0.7,
                'stream': False
            },
            timeout=300
        )
    else:
        response = requests.post(
            OLLAMA_HOST,
            json={
                'model': OLLAMA_MODEL,
                'messages': messages,
                'stream': False
            }
        )
    
    if response.status_code != 200:
        if response.status_code == 402:
            raise Exception(f"DeepSeek API 余额不足")
        else:
            raise Exception(f"API调用失败: {response.status_code} - {response.text}")
    
    # print("Response:", response.text)  # 打印完整响应
    
    try:
        response_data = response.json()
        
        if current_api == 'deepseek':
            if 'choices' in response_data and len(response_data['choices']) > 0:
                content = response_data['choices'][0]['message']['content'].strip()
            else:
                raise Exception("API响应格式错误：未找到choices字段")
        elif current_api == 'gemini':
            # 判断是否是 zenmux.ai 的 API（使用类似 DeepSeek 的响应格式）
            if GEMINI_HOST and ('zenmux.ai' in GEMINI_HOST or 'api/v1' in GEMINI_HOST):
                # zenmux.ai 格式（类似 DeepSeek）
                if 'choices' in response_data and len(response_data['choices']) > 0:
                    content = response_data['choices'][0]['message']['content'].strip()
                else:
                    raise Exception("API响应格式错误：未找到choices字段")
            else:
                # 标准 Gemini 格式
                if 'candidates' in response_data and len(response_data['candidates']) > 0:
                    if 'content' in response_data['candidates'][0] and 'parts' in response_data['candidates'][0]['content']:
                        content = response_data['candidates'][0]['content']['parts'][0]['text'].strip()
                    else:
                        raise Exception("API响应格式错误：未找到content.parts字段")
                else:
                    raise Exception("API响应格式错误：未找到candidates字段")
        else:
            if 'message' in response_data and 'content' in response_data['message']:
                content = response_data['message']['content'].strip()
            else:
                raise Exception("API响应格式错误：未找到message.content字段")
        
        # 使用正则表达式删除<think>标签及其内容
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        # print("Final content:", content)  # 打印最终内容
        return content.strip()
    except Exception as e:
        print("Error parsing response:", str(e))
        raise Exception(f"解析API响应失败: {str(e)}")

def _build_http_session():
    """
    构建更稳的 requests Session：
    1. 忽略系统代理环境变量，避免莫名其妙走到坏掉的代理
    2. 自动重试临时网络错误
    3. 关闭长连接复用带来的脏连接问题
    """
    session = requests.Session()
    session.trust_env = False  # 关键：忽略 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY

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
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


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
        # 有些兼容接口会返回分段结构
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
    """
    统一的 OpenAI 兼容接口请求函数：
    - DeepSeek 官方
    - zenmux.ai 这类中转
    """
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
                timeout=(10, 180),  # 连接超时10秒，读超时180秒
            )

            # 先尽量读 JSON；失败再回退到文本
            try:
                data = resp.json()
            except Exception:
                data = None

            if resp.status_code == 200:
                if data is None:
                    raise ValueError(f"{request_name} 返回200，但不是合法JSON")
                return _extract_openai_compatible_text(data)

            # 常见余额 / 鉴权 / 限流报错尽量给清楚点
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

        except ConnectionError as e:
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


def _call_deepseek(messages, temperature=0.8, max_tokens=2000):
    return _post_openai_compatible(
        host=DEEPSEEK_HOST,
        api_key=DEEPSEEK_API_KEY,
        model=DEEPSEEK_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        request_name="DeepSeek",
    )


def _call_gemini_compatible(messages, temperature=0.8, max_tokens=2000):
    return _post_openai_compatible(
        host=GEMINI_HOST,
        api_key=GEMINI_API_KEY,
        model=GEMINI_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        request_name="Gemini",
    )

def get_characters(script_id, character_id=0):
    """获取角色"""
    if character_id == 0:
        characters = CharacterModel.query.filter_by(script_id=script_id).all()
    else:
        characters = CharacterModel.query.filter_by(script_id=script_id).filter(CharacterModel.id != character_id).all()

    if not characters:
        characters_json = "无"
    else:
        # 将角色转换为字典列表
        characters_list = [
            {
                'name': character.name,
                'gender': character.gender,
                'age': character.age,
                'description': character.description,
                'personality': character.personality,
                'background': character.background,
                'relationships': character.relationships
            }
            for character in characters
        ]
        
        # 将角色列表转换为JSON字符串
        characters_json = json.dumps(characters_list, ensure_ascii=False)

    return characters_json

def get_chapters(script_id, end_number=0):
    """获取从end_number之前的五章"""
    if end_number == 0:
        chapters = ChapterModel.query.filter_by(script_id=script_id).order_by(ChapterModel.number.desc()).limit(5).all()
    else:
        chapters = ChapterModel.query.filter_by(script_id=script_id).filter(ChapterModel.number > end_number-5).limit(5).all()

    if not chapters:
        chapters_json = "无"
        from_number = 1
    else:    
        # 按章节编号排序
        chapters = sorted(chapters, key=lambda chapter: chapter.number)

        # 将章节转换为字典列表
        chapters_list = [
            {
                'number': chapter.number,
                'title': chapter.title,
                'chapter_outline': chapter.chapter_outline
            }
            for chapter in chapters
        ]
        
        # 将章节列表转换为JSON字符串
        chapters_json = json.dumps(chapters_list, ensure_ascii=False)
        from_number = chapters[-1].number + 1
    return chapters_json, from_number

def get_one_chapter(script_id, number):
    """获取指定章节"""
    chapter = ChapterModel.query.filter_by(script_id=script_id).filter(ChapterModel.number == number).first()
    return chapter

@api.route('/validate', methods=['POST'])
@login_required
def validate():
    """验证生成请求的参数"""
    data = request.get_json()
    field_name = data.get('field_name')
    optimize = data.get('optimize')

    try:
        # 加载并处理提示词模板
        prompt_template = load_prompt_template(field_name+optimize)
        
        # 解析模板中的字段
        required_fields = parse_template_fields(prompt_template)
        if 'history' in required_fields:
            required_fields.remove('history')
        # 检查是否所有必需字段都已提供且不为空
        missing_fields = [field for field in required_fields if field not in data or not data[field]]

        if missing_fields:
            return jsonify({
                'success': False,
                'status': 'validation_failed',
                'message': f'缺少必要字段或字段为空: {", ".join(missing_fields)}'
            })
        
        # 验证通过，返回成功状态
        return jsonify({
            'success': True,
            'status': 'validation_passed',
            'message': '验证通过'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'validation_failed',
            'message': str(e)
        })

@api.route('/generate', methods=['POST'])
@login_required
def generate():
    """执行内容生成"""
    data = request.get_json()
    field_name = data.get('field_name')
    optimize = data.get('optimize')

    try:

        # 加载并处理提示词模板
        prompt_template = load_prompt_template(field_name+optimize)
        
        # 替换模板中的字段
        prompt = prompt_template.format(**data)
        
        # 生成内容
        generated_content = call_api(prompt)
        
        return jsonify({
            'success': True,
            'status': 'generating_completed',
            'content': generated_content
        })
        
    except Exception as e:
        print(e)
        return jsonify({
            'success': False,
            'status': 'generating_failed',
            'message': str(e)
        })


@api.route('/generate/outline', methods=['POST'])
@login_required
def generate_outline():
    """生成大纲"""
    data = request.get_json()
    script_id = data.get('script_id')
    field_name = data.get('field_name')
    optimize = data.get('optimize')

    try:
        # 加载大纲生成提示词模板
        prompt_template = load_prompt_template(field_name+optimize)
        # 从数据库中获取当前故事的所有角色，替换模板中的{history}部分
        data['history'] = get_characters(script_id)
        prompt = prompt_template.format(**data)
        # 生成内容
        generated_content = call_api(prompt)
        
        return jsonify({
            'success': True,
            'status': 'generating_completed',
            'content': generated_content
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'generating_failed',
            'message': str(e)
        }) 

@api.route('/generate/chapter', methods=['POST'])
@login_required
def generate_chapter():
    """生成或优化章节的各项内容"""
    data = request.get_json()
    script_id = int(data.get('script_id'))
    field_name = data.get('field_name')
    optimize = data.get('optimize')
    number = int(data.get('number'))

    try:
        # 加载大纲生成提示词模板
        prompt_template = load_prompt_template(field_name+optimize)
        # 从数据库中获取当前故事的所有角色，替换模板中的{characters}部分
        data['characters'] = get_characters(script_id)
        # 从数据库中获取最近五章的大纲，替换模板中的{history}部分
        data['history'], _ = get_chapters(script_id, number-1)

        story = ScriptModel.query.filter_by(id=script_id).all()
        data['outline'] = story[0].outline
        data['background'] = story[0].background
        data['knowledge'] = story[0].knowledge
        data['write_style'] = story[0].write_style
        data['style'] = story[0].style
        # 从数据库中获取思维导图，替换模板中的{mind_map}部分
        mind_map = story[0].mind_map
        if mind_map == '' or mind_map == '无':
            mind_map = {}
        else:
            mind_map = json.loads(mind_map)
            for chapter in mind_map['data']['children']:
                if chapter['id'] == "chapter_"+str(number):
                    mind_map = chapter
                    break
        data['mind_map'] = json.dumps(mind_map, ensure_ascii=False)
        prompt = prompt_template.format(**data)
        # 生成内容
        generated_content = call_api(prompt)
        
        return jsonify({
            'success': True,
            'status': 'generating_completed',
            'content': generated_content
        })
        
    except Exception as e:
        print(e)
        return jsonify({
            'success': False,
            'status': 'generating_failed',
            'message': str(e)
        }) 

@api.route('/generate/mind', methods=['POST'])
@login_required
def generate_mind():
    """生成思维导图"""
    data = request.get_json()
    script_id = int(data.get('script_id'))
    title = data.get('title')
    field_name = data.get('field_name')

    try:
        # 加载思维导图生成提示词模板
        prompt_template = load_prompt_template(field_name)
        number = 1
        mind_map = {'title':title, 'chapters':[]}
        while True:
            chapter = get_one_chapter(script_id, number)
            data['title'] = chapter.title
            data['number'] = chapter.number
            data['outline'] = chapter.chapter_outline
            prompt = prompt_template.format(**data)
            generated_content = call_api(prompt)
            json_data = generated_content.replace('```json', '').replace('```', '')
            # 解析生成的JSON数组
            mind_map['chapters'].append(json.loads(json_data))
            number += 1
        mind_map_json = json.dumps(mind_map, ensure_ascii=False)
        print(mind_map_json)
        return jsonify({
            'success': True,
            'status': 'generating_completed',
            'mind_map': mind_map_json
        })
        
    except Exception as e:
        print(e)
        return jsonify({
            'success': False,
            'status': 'generating_failed',
            'message': str(e)
        }) 

@api.route('/generate/chapters', methods=['POST'])
@login_required
def generate_chapters():
    """生成章节"""
    data = request.get_json()
    script_id = data.get('script_id')
    number = int(data.get('chapters_count'))
    try:
        # 加载章节生成提示词模板
        prompt_template = load_prompt_template('chapters')
        # 从数据库中获取当前故事的所有角色，替换模板中的{characters}部分
        data['characters'] = get_characters(script_id)
        # 从数据库中获取当前故事的最近五章，替换模板中的{history}部分
        chapters, from_number = get_chapters(script_id)
        data['history'] = chapters
        data['from'] = from_number
        data['to'] = from_number + number - 1
        # 替换所有字段
        prompt = prompt_template.format(**data)
        # 生成内容
        generated_content = call_api(prompt)
        json_data = generated_content.replace('```json', '').replace('```', '')
        # 解析生成的JSON数组
        chapters = json.loads(json_data)
        # 保存角色到数据库
        for chapter_data in chapters:
            chapter = ChapterModel(
                script_id=int(script_id),
                number=int(chapter_data.get('number')),
                title=str(chapter_data.get('title')),
                chapter_outline=str(chapter_data.get('outline')),
                chapter_content='',
                chapter_script=''
            )
            db.session.add(chapter)
        
        # 提交事务
        db.session.commit()
        
        return jsonify({
            'success': True,
            'status': 'generating_completed',
            'message': f'成功生成 {len(chapters)} 个章节'
        })
        
    except json.JSONDecodeError:
        return jsonify({
            'success': False,
            'status': 'generating_failed',
            'message': '生成的内容不是有效的JSON格式'
        })
    except Exception as e:
        # 发生错误时回滚事务
        db.session.rollback()
        print(e)
        return jsonify({
            'success': False,
            'status': 'generating_failed',
            'message': str(e)
        }) 
    
@api.route('/generate/characters', methods=['POST'])
@login_required
def generate_characters():
    """生成角色"""
    data = request.get_json()
    script_id = data.get('script_id')
    
    try:
        # 加载角色生成提示词模板
        prompt_template = load_prompt_template('characters')
        # 从数据库中获取当前故事的所有角色
        # 替换模板中的{history}部分
        data['history'] = get_characters(script_id)
        prompt = prompt_template.format(**data)
        # 生成内容
        generated_content = call_api(prompt)
        json_data = generated_content.replace('```json', '').replace('```', '')
        # 解析生成的JSON数组
        characters = json.loads(json_data)
        # 保存角色到数据库
        for character_data in characters:
            character = CharacterModel(
                script_id=script_id,
                name=character_data.get('name', ''),
                gender=character_data.get('gender', '其他'),
                age=character_data.get('age'),
                description=character_data.get('description', ''),
                personality=character_data.get('personality', ''),
                background=character_data.get('background', ''),
                relationships=character_data.get('relationships', '')
            )
            db.session.add(character)
        
        # 提交事务
        db.session.commit()
        
        return jsonify({
            'success': True,
            'status': 'generating_completed',
            'message': f'成功生成 {len(characters)} 个角色'
        })
        
    except json.JSONDecodeError:
        return jsonify({
            'success': False,
            'status': 'generating_failed',
            'message': '生成的内容不是有效的JSON格式'
        })
    except Exception as e:
        # 发生错误时回滚事务
        db.session.rollback()
        return jsonify({
            'success': False,
            'status': 'generating_failed',
            'message': str(e)
        }) 
    
@api.route('/optimize/character', methods=['POST'])
@login_required
def optimize_character():
    """优化角色"""
    data = request.get_json()
    script_id = data.get('script_id')
    character_id = data.get('character_id')

    try:
        # 加载角色优化提示词模板
        prompt_template = load_prompt_template('character_optimize')
        # 从数据库中获取除了当前角色之外的其他角色，替换模板中的{history}部分
        data['history'] = get_characters(script_id, character_id)
        prompt = prompt_template.format(**data)
        # 生成内容
        generated_content = call_api(prompt)

        json_data = generated_content.replace('```json', '').replace('```', '')
        # 解析生成的JSON数组
        character_data = json.loads(json_data)
        # 保存角色到数据库
        character = CharacterModel.query.filter_by(id=character_id).first()
        character.description = character_data.get('description')
        character.personality = character_data.get('personality')
        character.background = character_data.get('background')
        character.relationships = character_data.get('relationships')
        # 直接提交更改，不需要调用update
        db.session.commit()
        
        return jsonify({
            'success': True,
            'status': 'generating_completed',
            'message': '成功优化角色',
            'description': character.description,
            'personality': character.personality,
            'background': character.background,
            'relationships': character.relationships
        })
        
    except json.JSONDecodeError:
        return jsonify({
            'success': False,
            'status': 'generating_failed',
            'message': '生成的内容不是有效的JSON格式'
        })
    except Exception as e:
        # 发生错误时回滚事务
        db.session.rollback()
        return jsonify({
            'success': False,
            'status': 'generating_failed',
            'message': str(e)
        })


@api.route('/validate_content', methods=['GET'])
@login_required
def validate_content():
    """验证故事内容或剧本内容"""
    try:
        script_id = request.args.get('script_id', type=int)
        content_type = request.args.get('type', 'story')  # 'story' 或 'script'
        
        if not script_id:
            return jsonify({
                'success': False,
                'message': '缺少script_id参数'
            }), 400
        
        # 获取剧本
        script = ScriptModel.query.get_or_404(script_id)
        if script.user_id != current_user.id:
            return jsonify({
                'success': False,
                'message': '您没有权限验证此剧本'
            }), 403
        
        # 根据类型获取内容
        if content_type == 'story':
            # 获取所有章节的故事内容
            chapters = ChapterModel.query.filter_by(script_id=script_id).order_by(ChapterModel.number).all()
            content = f"《{script.title}》\n\n"
            for chapter in chapters:
                content += f"\n第{chapter.number}章 {chapter.title}\n\n"
                if hasattr(chapter, 'chapter_content') and chapter.chapter_content:
                    content += chapter.chapter_content + "\n"
                else:
                    content += getattr(chapter, 'content', '(章节内容为空)') + "\n"
        elif content_type == 'script':
            # 获取所有章节的剧本内容
            chapters = ChapterModel.query.filter_by(script_id=script_id).order_by(ChapterModel.number).all()
            characters = CharacterModel.query.filter_by(script_id=script_id).all()
            content = f"《{script.title}》剧本\n\n"
            if characters:
                content += "【角色表】\n\n"
                for character in characters:
                    content += f"{character.name}: {character.gender}, {character.age}岁\n"
                    if character.description:
                        content += f"描述: {character.description}\n"
                    content += "\n"
            for chapter in chapters:
                content += f"\n第{chapter.number}章 {chapter.title}\n\n"
                if hasattr(chapter, 'chapter_script') and chapter.chapter_script:
                    content += chapter.chapter_script + "\n"
                else:
                    content += "(章节剧本内容为空)\n"
        else:
            return jsonify({
                'success': False,
                'message': '不支持的内容类型'
            }), 400
        
        # 加载验证提示词模板
        try:
            prompt_template = load_prompt_template('content_check')
        except FileNotFoundError:
            return jsonify({
                'success': False,
                'message': '验证提示词模板文件不存在'
            }), 500
        
        # 构建完整的提示词
        prompt = f"{prompt_template}\n\n【源文本】\n\n{content}"
        
        # 调用AI进行验证
        validation_result = call_api(prompt)
        
        return jsonify({
            'success': True,
            'validation_result': validation_result,
            'message': '验证完成'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'验证失败: {str(e)}'
        }), 500

# =========================
# Chat MVP API（追加到 api.py 文件末尾）
# =========================
# 任务内存存储（MVP 版）
# 注意：这是内存存储，服务重启后会丢失
DEFAULT_WORD_COUNT = "2"
CHAT_TASK_STORE = {}
CHAT_TASK_LOCK = threading.Lock()


def _set_chat_task(task_id, **kwargs):
    """线程安全地更新任务状态"""
    with CHAT_TASK_LOCK:
        task = CHAT_TASK_STORE.get(task_id, {})
        task["task_id"] = task_id
        task.update(kwargs)
        CHAT_TASK_STORE[task_id] = task


def _get_chat_task(task_id):
    """线程安全地读取任务状态"""
    with CHAT_TASK_LOCK:
        return CHAT_TASK_STORE.get(task_id)


def _normalize_tag_list(value):
    """把字符串 / 列表统一转成去重后的字符串列表"""
    if value is None:
        return []

    if isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        raw = re.split(r"[，,、/|；;]+", value)
    else:
        raw = [str(value)]

    result = []
    seen = set()
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _normalize_word_count_wan(value):
    try:
        v = float(value)
        if v <= 0:
            return DEFAULT_WORD_COUNT
        return v
    except Exception:
        return DEFAULT_WORD_COUNT


def _format_word_count_text(word_count_wan):
    if word_count_wan <= 0:
        word_count_wan = DEFAULT_WORD_COUNT
    return f"{word_count_wan}万字"


def _detect_input_mode(message, meta):
    """
    判断输入模式：
    1. free_generate 自由生成
    2. reskin 参考换皮
    3. framework 框架创作
    """
    reference_text = (meta.get("reference_text") or "").strip()
    framework_text = (meta.get("framework_text") or "").strip()

    if reference_text:
        return "reskin"
    if framework_text:
        return "framework"
    return "free_generate"


def _build_story_brief(message, meta, mode, user_id, project_id=None):
    """总编剧：统一整理需求书（前端极简输入版）"""

    word_count_wan = _normalize_word_count_wan(meta.get("word_count_wan"))

    return {
        "project_id": project_id,
        "user_id": user_id,
        "mode": mode,
        "user_message": (message or "").strip(),

        # 当前前端只保留这一个结构化参数
        "word_count_wan": word_count_wan,
        "word_count": _format_word_count_text(word_count_wan),

        # 这些字段先留空，后面交给输入分析器自动补
        "main_categories": [],
        "theme_tags": [],
        "character_tags": [],
        "plot_tags": [],
        "style_tags": [],
        "genre": "",
        "style": "",
        "reference_text": "",
        "framework_text": "",
        "banned": "",
        "output_granularity": "outline",

        "created_at": datetime.now(timezone.utc).isoformat()
    }


def _call_api_for_chat(prompt, selected_model=None):
    """
    专门给 Chat 流程使用的 LLM 调用函数。
    注意：不能直接调用你原来的 call_api()，因为它依赖 request/session，
    而这里的任务可能在后台线程里执行。
    """
    current_api = selected_model or API

    messages = [
        {
            "role": "system",
            "content": "你是一个专业的剧本创作智能体，擅长总编剧拆解、人物塑造、剧情大纲设计与商业化短剧审核。"
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    if current_api == 'deepseek':
        response = requests.post(
            DEEPSEEK_HOST,
            headers={
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': DEEPSEEK_MODEL,
                'messages': messages,
                'temperature': 0.7,
                'max_tokens': 8192,
                'stream': False
            },
            timeout=300
        )
    elif current_api == 'gemini':
        response = requests.post(
            GEMINI_HOST,
            headers={
                'Authorization': f'Bearer {GEMINI_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': GEMINI_MODEL,
                'messages': messages,
                'temperature': 0.7,
                'stream': False
            },
            timeout=300
        )
    else:
        response = requests.post(
            OLLAMA_HOST,
            json={
                'model': OLLAMA_MODEL,
                'messages': messages,
                'stream': False
            },
            timeout=300
        )

    if response.status_code != 200:
        if response.status_code == 402:
            raise Exception("模型 API 余额不足")
        raise Exception(f"API调用失败: {response.status_code} - {response.text}")

    response_data = response.json()

    if current_api == 'deepseek':
        if 'choices' in response_data and len(response_data['choices']) > 0:
            content = response_data['choices'][0]['message']['content'].strip()
        else:
            raise Exception("DeepSeek API 响应格式错误：未找到 choices")
    elif current_api == 'gemini':
        # 兼容 zenmux.ai 这类类 OpenAI 格式
        if GEMINI_HOST and ('zenmux.ai' in GEMINI_HOST or 'api/v1' in GEMINI_HOST):
            if 'choices' in response_data and len(response_data['choices']) > 0:
                content = response_data['choices'][0]['message']['content'].strip()
            else:
                raise Exception("Gemini API 响应格式错误：未找到 choices")
        else:
            if 'candidates' in response_data and len(response_data['candidates']) > 0:
                if 'content' in response_data['candidates'][0] and 'parts' in response_data['candidates'][0]['content']:
                    content = response_data['candidates'][0]['content']['parts'][0]['text'].strip()
                else:
                    raise Exception("Gemini API 响应格式错误：未找到 content.parts")
            else:
                raise Exception("Gemini API 响应格式错误：未找到 candidates")
    else:
        if 'message' in response_data and 'content' in response_data['message']:
            content = response_data['message']['content'].strip()
        else:
            raise Exception("Ollama API 响应格式错误：未找到 message.content")

    # 去掉 think 标签
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
    return content.strip()


def _generate_character_bible(story_brief, selected_model=None):
    """编剧 A：生成角色设定"""
    prompt = f"""
    你是编剧A（人物编剧）。
    请根据下面的需求书，输出结构化的人物设定。

    【需求书】
    模式：{story_brief['mode']}
    主分类：{'、'.join(story_brief['main_categories']) if story_brief['main_categories'] else '未指定'}
    主题标签：{'、'.join(story_brief['theme_tags']) if story_brief['theme_tags'] else '未指定'}
    角色标签：{'、'.join(story_brief['character_tags']) if story_brief['character_tags'] else '未指定'}
    情节标签：{'、'.join(story_brief['plot_tags']) if story_brief['plot_tags'] else '未指定'}
    综合风格：{story_brief['style']}
    字数/集数要求：{story_brief['word_count']}
    用户需求：{story_brief['user_message']}
    参考内容：{story_brief['reference_text']}
    框架内容：{story_brief['framework_text']}
    禁止项：{story_brief['banned']}

    要求：
    1. 允许多分类融合，但必须有主次，不要平均发力
    2. 人物必须服务于主分类和核心冲突
    3. 输出要偏短篇小说/短剧可执行，不要空泛设定
    4. 如果标签存在冲突，优先保证“用户需求一句话”和主分类成立

    请输出：
    1. 主角
    2. 核心配角
    3. 反派/对立面
    4. 人物关系
    5. 每个角色的欲望、弱点、成长线
    6. 角色卖点与情绪钩子

    请用清晰的小标题输出。
    """

    try:
        content = _call_api_for_chat(prompt, selected_model=selected_model)
    except Exception as e:
        raise Exception(f"人物设定生成失败：{str(e)}")

    if not content or "兜底版" in content or "待定主角" in content:
        raise Exception("人物设定生成失败：模型返回了无效模板内容")

    return {
        "raw_text": content,
        "summary": content[:300]
    }


def _generate_plot_outline(story_brief, character_bible, selected_model=None):
    """编剧 B：生成剧情大纲"""
    prompt = f"""
    你是编剧B（剧情编剧）。
    请基于用户需求和人物设定，输出适合短篇小说 / 短剧开发的剧情结构。

    【需求书】
    模式：{story_brief['mode']}
    主分类：{'、'.join(story_brief['main_categories']) if story_brief['main_categories'] else '未指定'}
    主题标签：{'、'.join(story_brief['theme_tags']) if story_brief['theme_tags'] else '未指定'}
    角色标签：{'、'.join(story_brief['character_tags']) if story_brief['character_tags'] else '未指定'}
    情节标签：{'、'.join(story_brief['plot_tags']) if story_brief['plot_tags'] else '未指定'}
    综合风格：{story_brief['style']}
    字数/集数要求：{story_brief['word_count']}
    用户需求：{story_brief['user_message']}
    禁止项：{story_brief['banned']}

    【人物设定】
    {character_bible['raw_text']}

    要求：
    1. 支持“都市 + 玄幻仙侠”这类多分类融合，但必须明确主线世界观
    2. 默认按短篇小说体量组织结构，用户若明确指定再按其要求调整
    3. 开头必须强钩子，尽快建立冲突和追更点
    4. 不能只堆设定，必须有推进、反转、悬念

    请输出：
    1. 一句话 Logline
    2. 开头强钩子（前3秒/前30秒）
    3. 核心矛盾
    4. 剧情大纲（分阶段）
    5. 每集/每阶段钩子
    6. 关键反转
    7. 付费点/追更点
    8. 最终结局方向

    请用清晰的小标题输出。
    """

    try:
        content = _call_api_for_chat(prompt, selected_model=selected_model)
    except Exception as e:
        raise Exception(f"情节大纲生成失败：{str(e)}")

    if not content or "兜底版" in content or "待定情节" in content:
        raise Exception("情节大纲生成失败：模型返回了无效模板内容")

    return {
        "raw_text": content,
        "summary": content[:300]
    }


def _review_artifacts(story_brief, character_bible, plot_outline, selected_model=None):
    """审核模块：输出审核报告"""
    prompt = f"""
你是短剧审核官。
请根据下面内容输出审核报告。

【需求书】
题材：{story_brief['genre']}
风格：{story_brief['style']}
用户需求：{story_brief['user_message']}
禁止项：{story_brief['banned']}

【人物设定】
{character_bible['raw_text']}

【剧情大纲】
{plot_outline['raw_text']}

请按下面结构输出：
1. 总评分（100分）
2. 开头钩子评分
3. 主角压力评分
4. 情绪拉力评分
5. 冲突推进评分
6. 下一集诱因评分
7. 主要问题
8. 修改建议
9. 是否需要重写（是/否）
10. 建议退回给谁（chief_editor / character_writer / plot_writer）
"""

    try:
        content = _call_api_for_chat(prompt, selected_model=selected_model)
    except Exception as e:
        raise Exception(f"审核生成失败：{str(e)}")

    if not content or "兜底版" in content or "待定" in content:
        raise Exception("审核生成失败：模型返回了无效模板内容")

    return {
        "raw_text": content,
        "summary": content[:300]
    }


def _assemble_final_script(story_brief, character_bible, plot_outline, review_report):
    """组装最终返回给前端的产物"""
    final_script = f"""
# 最终剧本产物（MVP）

## 用户需求
{story_brief['user_message']}

## 人物设定
{character_bible['raw_text']}

## 剧情大纲
{plot_outline['raw_text']}

## 审核报告
{review_report['raw_text']}
""".strip()

    return {
        "final_script": final_script,
        "character_bible": character_bible["raw_text"],
        "plot_outline": plot_outline["raw_text"],
        "review_report": review_report["raw_text"]
    }


def _get_or_create_project(user_id, project_id, story_brief):
    """
    如果用户传了 project_id，就更新现有项目；
    如果没传，就自动创建一个最小项目。
    """
    if project_id:
        script = ScriptModel.query.get(project_id)
        if not script:
            raise Exception("project_id 对应的项目不存在")
        if script.user_id != user_id:
            raise Exception("无权操作该项目")
        return script

    # 自动创建最小项目
    title = (story_brief["user_message"] or "新建剧本")[:20]
    script = ScriptModel(
        title=title,
        content=story_brief["user_message"] or "新建剧本内容",
        word_count=0,
        style_type='2d_realistic',
        write_style=story_brief.get("style", "") or "无",
        has_branching=False,
        genre=story_brief.get("genre", "") or "",
        background=story_brief.get("framework_text", "") or "",
        user_id=user_id
    )
    db.session.add(script)
    db.session.commit()
    return script


def _persist_artifacts_to_project(script, story_brief, artifacts):
    """
    把结果写回旧表，实现“旧页面降级成查看/编辑页”：
    1. ScriptModel 作为总容器
    2. CharacterModel / ChapterModel 至少生成一批可查看/可编辑的旧页记录
    """
    # 1）先写 ScriptModel 总字段
    script.background = story_brief.get("framework_text", "") or script.background or ""
    script.knowledge = story_brief.get("reference_text", "") or script.knowledge or ""
    script.style = story_brief.get("style", "") or script.style or ""
    script.write_style = story_brief.get("style", "") or script.write_style or ""
    script.genre = story_brief.get("genre", "") or script.genre or ""
    script.outline = artifacts.get("plot_outline", "") or script.outline or ""
    script.characters = artifacts.get("character_bible", "") or script.characters or ""
    script.relationships = artifacts.get("character_bible", "")[:1000] or script.relationships or ""
    script.content = artifacts.get("final_script", "") or script.content or ""

    db.session.commit()

    # 2）清空旧的角色和章节（MVP：每次重新覆盖）
    CharacterModel.query.filter_by(script_id=script.id).delete()
    ChapterModel.query.filter_by(script_id=script.id).delete()
    db.session.commit()

    # 3）把人物设定同步成旧角色表
    character_text = artifacts.get("character_bible", "") or ""
    _sync_character_bible_to_legacy_table(script.id, character_text)

    # 4）把剧情大纲同步成旧章节表
    outline_text = artifacts.get("plot_outline", "") or ""
    _sync_outline_to_legacy_chapters(script.id, outline_text)

    db.session.commit()


def _sync_character_bible_to_legacy_table(script_id, character_text):
    """
    把人物设定文本同步成 CharacterModel
    MVP 规则：
    - 如果能识别出多个“## 人物名”块，就拆成多角色
    - 如果拆不出来，就至少生成一个“角色总表”
    """
    text = (character_text or "").strip()
    if not text:
        return

    # 优先按 Markdown 二级标题拆分
    blocks = re.split(r'\n##\s+', '\n' + text)
    parsed = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.splitlines()
        first_line = lines[0].strip()

        # 跳过总标题
        if "人物设定" in first_line and len(lines) == 1:
            continue

        # 尝试提取角色名
        name = first_line
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        # 如果标题太长，不像人名，则放弃当角色块
        if len(name) > 20 and not body:
            continue

        parsed.append({
            "name": name[:100],
            "description": body[:3000] if body else block[:3000]
        })

    # 如果拆不出来，就生成一个总表角色
    if not parsed:
        parsed = [{
            "name": "角色总表",
            "description": text[:3000]
        }]

    for item in parsed[:10]:
        character = CharacterModel(
            script_id=script_id,
            name=item["name"] or "未命名角色",
            gender="",
            age=None,
            description=item["description"],
            personality=item["description"][:1000],
            background=item["description"][:1000],
            relationships=item["description"][:1000]
        )
        db.session.add(character)


def _sync_outline_to_legacy_chapters(script_id, outline_text):
    """
    把剧情大纲同步成 ChapterModel
    MVP 规则：
    - 先尝试按“第X集 / 第X章 / ## 标题”拆分
    - 如果拆不出来，就生成一个“剧情大纲总表”章节
    """
    text = (outline_text or "").strip()
    if not text:
        return

    parts = []

    # 尝试按“第X集 / 第X章”切
    ep_parts = re.split(r'\n(?=第[0-9一二三四五六七八九十百]+[集章节])', text)
    if len(ep_parts) > 1:
        for idx, part in enumerate(ep_parts, start=1):
            part = part.strip()
            if not part:
                continue
            title_line = part.splitlines()[0].strip()
            parts.append({
                "number": idx,
                "title": title_line[:200],
                "outline": part[:10000]
            })
    else:
        # 再尝试按 Markdown 二级标题切
        md_parts = re.split(r'\n##\s+', '\n' + text)
        for idx, part in enumerate(md_parts, start=1):
            part = part.strip()
            if not part:
                continue
            lines = part.splitlines()
            title = lines[0].strip()[:200]
            body = "\n".join(lines[1:]).strip() if len(lines) > 1 else part
            parts.append({
                "number": idx,
                "title": title or f"第{idx}部分",
                "outline": body[:10000]
            })

    # 如果还是没拆出来，就给一个总表
    if not parts:
        parts = [{
            "number": 1,
            "title": "剧情大纲总表",
            "outline": text[:10000]
        }]

    for item in parts[:20]:
        chapter = ChapterModel(
            number=item["number"],
            title=item["title"] or f"第{item['number']}章",
            chapter_outline=item["outline"] or "暂无章节大纲",
            chapter_content="",
            chapter_script="",
            script_id=script_id
        )
        db.session.add(chapter)


def _run_chat_pipeline_async(flask_app, task_id, session_id, user_id, project_id, message, meta, selected_model):
    """
    后台线程执行任务
    """
    with flask_app.app_context():
        try:
            _set_chat_task(
                task_id=task_id,
                session_id=session_id,
                project_id=project_id,
                status="running",
                current_stage="chief_editor",
                progress=10,
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
                artifacts=None,
                trace=[]
            )

            mode = _detect_input_mode(message, meta)
            story_brief = _build_story_brief(message, meta, mode, user_id, project_id=project_id)

            trace = [{
                "stage": "chief_editor",
                "summary": f"已识别模式：{mode}",
                "time": datetime.now(timezone.utc).isoformat()
            }]

            script = _get_or_create_project(user_id, project_id, story_brief)
            project_id = script.id

            _set_chat_task(
                task_id,
                project_id=project_id,
                status="running",
                current_stage="character_writer",
                progress=30,
                updated_at=datetime.now(timezone.utc).isoformat(),
                trace=trace
            )

            character_bible = _generate_character_bible(story_brief, selected_model=selected_model)
            trace.append({
                "stage": "character_writer",
                "summary": character_bible["summary"],
                "time": datetime.now(timezone.utc).isoformat()
            })

            _set_chat_task(
                task_id,
                project_id=project_id,
                status="running",
                current_stage="plot_writer",
                progress=55,
                updated_at=datetime.now(timezone.utc).isoformat(),
                trace=trace
            )

            plot_outline = _generate_plot_outline(story_brief, character_bible, selected_model=selected_model)
            trace.append({
                "stage": "plot_writer",
                "summary": plot_outline["summary"],
                "time": datetime.now(timezone.utc).isoformat()
            })

            _set_chat_task(
                task_id,
                project_id=project_id,
                status="reviewing",
                current_stage="reviewer",
                progress=75,
                updated_at=datetime.now(timezone.utc).isoformat(),
                trace=trace
            )

            review_report = _review_artifacts(story_brief, character_bible, plot_outline, selected_model=selected_model)
            trace.append({
                "stage": "reviewer",
                "summary": review_report["summary"],
                "time": datetime.now(timezone.utc).isoformat()
            })

            # 第一版：最多自动回修一次
            if review_report.get("rewrite_required"):
                _set_chat_task(
                    task_id,
                    project_id=project_id,
                    status="retrying",
                    current_stage="plot_writer",
                    progress=85,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    trace=trace
                )

                retry_meta = dict(meta)
                retry_meta["banned"] = ((meta.get("banned") or "") + "；请加强开头钩子、冲突推进和追更点").strip("；")
                retry_brief = _build_story_brief(message, retry_meta, mode, user_id, project_id=project_id)

                plot_outline = _generate_plot_outline(retry_brief, character_bible, selected_model=selected_model)
                trace.append({
                    "stage": "plot_writer_retry",
                    "summary": plot_outline["summary"],
                    "time": datetime.now(timezone.utc).isoformat()
                })

                review_report = _review_artifacts(retry_brief, character_bible, plot_outline, selected_model=selected_model)
                trace.append({
                    "stage": "reviewer_retry",
                    "summary": review_report["summary"],
                    "time": datetime.now(timezone.utc).isoformat()
                })

                story_brief = retry_brief

            artifacts = _assemble_final_script(story_brief, character_bible, plot_outline, review_report)
            _persist_artifacts_to_project(script, story_brief, artifacts)

            _set_chat_task(
                task_id,
                project_id=project_id,
                status="done",
                current_stage="done",
                progress=100,
                updated_at=datetime.now(timezone.utc).isoformat(),
                artifacts={
                    "story_brief": story_brief,
                    **artifacts
                },
                trace=trace
            )

        except Exception as e:
            _set_chat_task(
                task_id,
                status="failed",
                current_stage="failed",
                progress=100,
                updated_at=datetime.now(timezone.utc).isoformat(),
                error=str(e),
                traceback=traceback.format_exc()
            )


def _allowed_reference_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_REFERENCE_EXTENSIONS


def _truncate_reference_text(text, max_chars=MAX_REFERENCE_TEXT_CHARS):
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars]

# 接下来的函数是分析用户输入的参考剧本的，有纯文本输入，网页链接，PDF的桑模式
def _extract_text_from_pdf_bytes(file_bytes):
    reader = PdfReader(BytesIO(file_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return _truncate_reference_text("\n".join(parts))


def _extract_text_from_plain_bytes(file_bytes):
    try:
        return _truncate_reference_text(file_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        try:
            return _truncate_reference_text(file_bytes.decode("gbk"))
        except Exception:
            return _truncate_reference_text(file_bytes.decode("utf-8", errors="ignore"))


def _extract_main_text_from_html(html):
    soup = BeautifulSoup(html, "html.parser")

    # 去掉噪音标签
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg", "iframe"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)
    return _truncate_reference_text(text)


def _fetch_reference_from_url(url):
    # Requests 官方建议显式设置 timeout
    resp = requests.get(url, timeout=(5, 20), headers={
        "User-Agent": "Mozilla/5.0 ScriptMaker Internal Bot"
    })
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "").lower()

    # 如果是 PDF 链接
    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        return _extract_text_from_pdf_bytes(resp.content)

    # 默认按 HTML 处理
    html = resp.text
    return _extract_main_text_from_html(html)


@api.route("/reference/ingest", methods=["POST"])
@login_required
def ingest_reference():
    """
    读取参考素材：
    1. 网页链接
    2. 上传文件（pdf/txt/md）
    最终统一返回 reference_text
    """
    try:
        # JSON 模式：网页链接
        if request.content_type and request.content_type.startswith("application/json"):
            data = request.get_json(silent=True) or {}
            ingest_type = (data.get("type") or "").strip()

            if ingest_type != "url":
                return jsonify({
                    "success": False,
                    "message": "JSON 模式仅支持 type=url"
                }), 400

            url = (data.get("url") or "").strip()
            if not url:
                return jsonify({
                    "success": False,
                    "message": "url 不能为空"
                }), 400

            reference_text = _fetch_reference_from_url(url)
            if not reference_text:
                return jsonify({
                    "success": False,
                    "message": "未能从网页中提取到正文内容"
                }), 400

            return jsonify({
                "success": True,
                "reference_text": reference_text,
                "source_type": "url",
                "source_name": url
            })

        # multipart/form-data 模式：上传文件
        ingest_type = (request.form.get("type") or "").strip()
        if ingest_type != "file":
            return jsonify({
                "success": False,
                "message": "文件模式必须传 type=file"
            }), 400

        if "file" not in request.files:
            return jsonify({
                "success": False,
                "message": "没有上传文件"
            }), 400

        file = request.files["file"]
        if not file or not file.filename:
            return jsonify({
                "success": False,
                "message": "文件名为空"
            }), 400

        filename = secure_filename(file.filename)
        if not _allowed_reference_file(filename):
            return jsonify({
                "success": False,
                "message": "仅支持 pdf / txt / md"
            }), 400

        ext = filename.rsplit(".", 1)[1].lower()
        file_bytes = file.read()

        if ext == "pdf":
            reference_text = _extract_text_from_pdf_bytes(file_bytes)
        else:
            reference_text = _extract_text_from_plain_bytes(file_bytes)

        if not reference_text:
            return jsonify({
                "success": False,
                "message": "未能从文件中提取到正文内容"
            }), 400

        return jsonify({
            "success": True,
            "reference_text": reference_text,
            "source_type": "file",
            "source_name": filename
        })

    except requests.exceptions.Timeout:
        return jsonify({
            "success": False,
            "message": "读取网页超时，请稍后重试"
        }), 504
    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "message": f"网页抓取失败：{str(e)}"
        }), 400
    except Exception as e:
        logging.error(f"读取参考素材失败: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"读取参考素材失败：{str(e)}"
        }), 500


@api.route('/chat/send', methods=['POST'])
@login_required
def chat_send():
    """
    用户发送消息，触发一次完整创作流程
    """
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    meta = data.get('meta') or {}
    project_id = data.get('project_id')
    selected_model = session.get('selected_model', API)

    if not message:
        return jsonify({
            'success': False,
            'message': 'message 不能为空'
        }), 400

    task_id = uuid.uuid4().hex
    session_id = uuid.uuid4().hex

    _set_chat_task(
        task_id,
        session_id=session_id,
        project_id=project_id,
        status="pending",
        current_stage="queued",
        progress=0,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        trace=[],
        artifacts=None
    )

    flask_app = current_app._get_current_object()
    thread = threading.Thread(
        target=_run_chat_pipeline_async,
        args=(flask_app, task_id, session_id, current_user.id, project_id, message, meta, selected_model),
        daemon=True
    )
    thread.start()

    return jsonify({
        'success': True,
        'task_id': task_id,
        'session_id': session_id,
        'status': 'pending',
        'mode': _detect_input_mode(message, meta)
    })


@api.route('/model/current', methods=['GET'])
@login_required
def get_current_model():
    selected_model = session.get('selected_model', API)
    return jsonify({
        'success': True,
        'selected_model': selected_model,
        'available_models': ['deepseek', 'gemini', 'ollama']
    })


@api.route('/model/select', methods=['POST'])
@login_required
def set_current_model():
    data = request.get_json(silent=True) or {}
    model = (data.get('model') or '').strip().lower()

    allowed = {'deepseek', 'gemini', 'ollama'}
    if model not in allowed:
        return jsonify({
            'success': False,
            'message': '不支持的模型'
        }), 400

    session['selected_model'] = model
    return jsonify({
        'success': True,
        'selected_model': model
    })


@api.route('/task/<task_id>', methods=['GET'])
@login_required
def get_task_status(task_id):
    """
    查询任务状态
    """
    task = _get_chat_task(task_id)
    if not task:
        return jsonify({
            'success': False,
            'message': '任务不存在'
        }), 404

    return jsonify({
        'success': True,
        'task_id': task.get('task_id'),
        'session_id': task.get('session_id'),
        'project_id': task.get('project_id'),
        'status': task.get('status'),
        'current_stage': task.get('current_stage'),
        'progress': task.get('progress', 0),
        'error': task.get('error'),
        'updated_at': task.get('updated_at')
    })


@api.route('/project/<int:project_id>/artifacts', methods=['GET'])
@login_required
def get_project_artifacts(project_id):
    """
    获取本次创作的全部产物
    """
    script = ScriptModel.query.get_or_404(project_id)
    if script.user_id != current_user.id:
        return jsonify({
            'success': False,
            'message': '您没有权限访问该项目'
        }), 403

    # 先从内存任务里找最近一次结果，没有就从数据库读
    latest_artifacts = None
    with CHAT_TASK_LOCK:
        for _, task in CHAT_TASK_STORE.items():
            if task.get('project_id') == project_id and task.get('status') == 'done':
                latest_artifacts = task.get('artifacts')
                break

    if latest_artifacts:
        return jsonify({
            'success': True,
            'project_id': project_id,
            'final_script': latest_artifacts.get('final_script', ''),
            'character_bible': latest_artifacts.get('character_bible', ''),
            'plot_outline': latest_artifacts.get('plot_outline', ''),
            'review_report': latest_artifacts.get('review_report', ''),
            'story_brief': latest_artifacts.get('story_brief', {})
        })

    # 数据库兜底
    return jsonify({
        'success': True,
        'project_id': project_id,
        'final_script': script.content or '',
        'character_bible': script.characters or '',
        'plot_outline': script.outline or '',
        'review_report': '',
        'story_brief': {
            'genre': script.genre or '',
            'style': script.style or script.write_style or '',
            'background': script.background or '',
            'knowledge': script.knowledge or ''
        }
    })


@api.route('/project/<int:project_id>/trace', methods=['GET'])
@login_required
def get_project_trace(project_id):
    """
    获取过程摘要
    """
    script = ScriptModel.query.get_or_404(project_id)
    if script.user_id != current_user.id:
        return jsonify({
            'success': False,
            'message': '您没有权限访问该项目'
        }), 403

    latest_trace = []
    latest_task_id = None
    latest_status = None

    with CHAT_TASK_LOCK:
        for task_id, task in CHAT_TASK_STORE.items():
            if task.get('project_id') == project_id:
                latest_trace = task.get('trace', [])
                latest_task_id = task_id
                latest_status = task.get('status')

    return jsonify({
        'success': True,
        'project_id': project_id,
        'task_id': latest_task_id,
        'status': latest_status,
        'trace': latest_trace
    })

