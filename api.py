# ============================================================
# Chat MVP API（问题2）作用与操作说明
# ============================================================
#
# 一、这组新增接口的作用
#
# 这 4 个接口是把原来“分散的生成按钮接口”，先整合成一个最小可用的
# 聊天式创作流程入口，方便后面接聊天页前端。
#
# 1. POST /api/chat/send
#    - 用户发一条消息，触发一次完整创作流程
#    - 后端会：
#      ① 识别输入模式（自由生成 / 参考换皮 / 框架创作）
#      ② 创建 task_id 和 session_id
#      ③ 启动后台线程执行流程
#      ④ 返回任务状态
#
# 2. GET /api/task/<task_id>
#    - 查询当前任务执行到哪一步
#    - 可返回：
#      pending / running / reviewing / retrying / done / failed
#
# 3. GET /api/project/<project_id>/artifacts
#    - 获取本次创作的最终产物
#    - 包括：
#      最终剧本、人物设定、剧情大纲、审核报告、story_brief
#
# 4. GET /api/project/<project_id>/trace
#    - 获取本次创作的过程摘要
#    - 包括：
#      总编剧拆解、人物编剧摘要、剧情编剧摘要、审核摘要
#
#
# 二、当前这版的实现方式（MVP 特点）
#
# 1. 任务状态(task)和过程(trace)先存放在内存里：
#    CHAT_TASK_STORE
#
# 2. 服务重启后，内存任务状态和 trace 会丢失
#    - 这是 MVP 阶段允许的
#    - 目的是先把聊天链路跑通
#
# 3. 虽然 task/trace 存在内存里，但主要结果会写回数据库：
#    - ScriptModel.content
#    - ScriptModel.outline
#    - ScriptModel.characters
#    - ScriptModel.background
#    - ScriptModel.knowledge
#    - ScriptModel.style / write_style
#
# 4. 这样做的意义是：
#    - 即使 Flask 重启，最终剧本、人设、大纲仍然会保留
#    - 旧页面（dashboard / chapters / characters）后续还能继续查看或编辑
#
#
# 三、前端以后怎么接这组接口
#
# 聊天页前端只需要按这个顺序调用：
#
# 1. 先调 POST /api/chat/send
#    - 提交用户输入
#    - 拿到 task_id、session_id、mode
#
# 2. 然后轮询 GET /api/task/<task_id>
#    - 看任务是否完成
#
# 3. 当 status == done 时：
#    - 请求 GET /api/project/<project_id>/artifacts
#    - 取最终剧本、人设、大纲、审核报告
#
# 4. 如果用户想看过程：
#    - 请求 GET /api/project/<project_id>/trace
#
#
# 四、目前这组接口内部的最小流程
#
# chat/send
#   -> detect_mode()                # 判断输入模式
#   -> _build_story_brief()         # 总编剧整理需求
#   -> _generate_character_bible()  # 编剧A生成人设
#   -> _generate_plot_outline()     # 编剧B生成剧情
#   -> _review_artifacts()          # 审核报告
#   -> 必要时自动回修一次
#   -> _persist_artifacts_to_project() 写回 ScriptModel
#
#
# 五、怎么测试（后端联调）
#
# 1. 重启 Flask
#    停掉服务后重新执行：
#
#       python app.py
#
# 2. Postman 测 POST /api/chat/send
#    地址：
#
#       http://127.0.0.1:60002/api/chat/send
#
#    Body 选 raw -> JSON，示例：
#
#       {
#         "project_id": null,
#         "message": "我要一个都市情感女频短剧，强调开头强钩子和连续反转",
#         "meta": {
#           "genre": "都市情感",
#           "style": "女频短剧",
#           "word_count": "80集",
#           "reference_text": "",
#           "framework_text": "",
#           "banned": "不要失忆梗",
#           "output_granularity": "outline"
#         }
#       }
#
# 3. 拿到 task_id 后，测任务状态：
#
#       GET http://127.0.0.1:60002/api/task/<task_id>
#
# 4. 拿到 project_id 后，测最终结果：
#
#       GET http://127.0.0.1:60002/api/project/<project_id>/artifacts
#
# 5. 查看过程摘要：
#
#       GET http://127.0.0.1:60002/api/project/<project_id>/trace
#
#
# 六、注意事项
#
# 1. 这版是 MVP，不是最终版
# 2. task / trace 暂时不落库
# 3. 主要目的是先把聊天入口打通
# 4. 后续可以把 CHAT_TASK_STORE 改成数据库表：
#    conversation_session / generation_task / agent_trace 等
# 5. 后续也可以把“人物 / 剧情 / 审核”从 api.py 再拆到
#    orchestrator/、agents/、review/、services/ 目录中
#
# 七、时间写法说明
#
# 如果看到 datetime.utcnow() 有 IDE 划线，这是因为它在 Python 3.12+
# 已被标记为 deprecated。
#
# 推荐把：
#    datetime.utcnow().isoformat()
#
# 改成：
#    datetime.now(timezone.utc).isoformat()
#
# 并确保文件顶部导入：
#    from datetime import datetime, timezone
#
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
from datetime import datetime
from flask import current_app

from urllib.parse import urlparse
from models import CharacterModel, ChapterModel, ScriptModel, db
from flask import Blueprint, request, jsonify, session
from flask_login import login_required, current_user

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

@api.route('/model/current', methods=['GET'])
@login_required
def get_current_model():
    """获取当前选择的模型"""
    current_model = session.get('selected_model', API or 'deepseek')
    return jsonify({
        'success': True,
        'model': current_model
    })

@api.route('/model/set', methods=['POST'])
@login_required
def set_current_model():
    """设置当前选择的模型"""
    data = request.get_json()
    model = data.get('model')
    
    if model not in ['deepseek', 'gemini']:
        return jsonify({
            'success': False,
            'message': '不支持的模型类型'
        })
    
    session['selected_model'] = model
    return jsonify({
        'success': True,
        'model': model,
        'message': f'已切换到 {model}'
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
CHAT_TASK_STORE = {}
CHAT_TASK_LOCK = threading.Lock()


def _set_chat_task(task_id, **kwargs):
    """线程安全地更新任务状态"""
    with CHAT_TASK_LOCK:
        task = CHAT_TASK_STORE.get(task_id, {})
        task.update(kwargs)
        CHAT_TASK_STORE[task_id] = task


def _get_chat_task(task_id):
    """线程安全地读取任务状态"""
    with CHAT_TASK_LOCK:
        return CHAT_TASK_STORE.get(task_id)


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
    """总编剧：统一整理需求书"""
    return {
        "project_id": project_id,
        "user_id": user_id,
        "mode": mode,
        "user_message": (message or "").strip(),
        "genre": (meta.get("genre") or "").strip(),
        "style": (meta.get("style") or "").strip(),
        "word_count": (meta.get("word_count") or "").strip(),
        "reference_text": (meta.get("reference_text") or "").strip(),
        "framework_text": (meta.get("framework_text") or "").strip(),
        "banned": (meta.get("banned") or "").strip(),
        "output_granularity": (meta.get("output_granularity") or "outline").strip(),
        "created_at": datetime.utcnow().isoformat()
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
题材：{story_brief['genre']}
风格：{story_brief['style']}
字数/集数要求：{story_brief['word_count']}
用户需求：{story_brief['user_message']}
参考内容：{story_brief['reference_text']}
框架内容：{story_brief['framework_text']}
禁止项：{story_brief['banned']}

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
    except Exception:
        content = f"""# 人物设定（兜底版）

## 主角
- 名称：待定主角
- 欲望：实现核心目标
- 弱点：情绪与现实压力并存
- 成长线：从被动承受到主动破局

## 核心配角
- 配角A：推动主线
- 配角B：制造阻力
- 配角C：提供情绪价值

## 人物关系
- 主角与对立面：高压冲突
- 主角与盟友：互相成就
"""

    return {
        "raw_text": content,
        "summary": content[:300]
    }


def _generate_plot_outline(story_brief, character_bible, selected_model=None):
    """编剧 B：生成剧情大纲"""
    prompt = f"""
你是编剧B（剧情编剧）。
请基于用户需求和人物设定，输出适合短剧的剧情结构。

【需求书】
模式：{story_brief['mode']}
题材：{story_brief['genre']}
风格：{story_brief['style']}
字数/集数要求：{story_brief['word_count']}
用户需求：{story_brief['user_message']}
禁止项：{story_brief['banned']}

【人物设定】
{character_bible['raw_text']}

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
    except Exception:
        content = f"""# 剧情大纲（兜底版）

## Logline
一个带有高压冲突与连续反转的短剧故事。

## 开头强钩子
主角在开场即遭遇重大危机，被迫进入主线冲突。

## 核心矛盾
主角目标与现实阻力正面碰撞，推动后续剧情升级。

## 剧情结构
- 第一阶段：建立人设与冲突
- 第二阶段：误判与升级
- 第三阶段：反转与代价
- 第四阶段：高潮与收束

## 追更点
每阶段结尾设置悬念与情绪钩子。
"""

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
        rewrite_required = ("是否需要重写：是" in content) or ("rewrite_required: true" in content.lower())
    except Exception:
        content = """# 审核报告（兜底版）

- 总评分：78
- 开头钩子：80
- 主角压力：75
- 情绪拉力：76
- 冲突推进：79
- 下一集诱因：80
- 主要问题：中段推进略慢
- 修改建议：加强中段冲突密度
- 是否需要重写：否
- 建议退回给谁：plot_writer
"""
        rewrite_required = False

    return {
        "raw_text": content,
        "summary": content[:300],
        "rewrite_required": rewrite_required
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
    把结果写回现有 ScriptModel，方便旧页面继续查看/编辑
    """
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


def _run_chat_pipeline_async(flask_app, task_id, session_id, user_id, project_id, message, meta, selected_model):
    """
    后台线程执行任务
    """
    with flask_app.app_context():
        try:
            _set_chat_task(
                task_id,
                task_id=task_id,
                session_id=session_id,
                project_id=project_id,
                status="running",
                current_stage="chief_editor",
                progress=10,
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
                artifacts=None,
                trace=[]
            )

            mode = _detect_input_mode(message, meta)
            story_brief = _build_story_brief(message, meta, mode, user_id, project_id=project_id)

            trace = [{
                "stage": "chief_editor",
                "summary": f"已识别模式：{mode}",
                "time": datetime.utcnow().isoformat()
            }]

            script = _get_or_create_project(user_id, project_id, story_brief)
            project_id = script.id

            _set_chat_task(
                task_id,
                project_id=project_id,
                status="running",
                current_stage="character_writer",
                progress=30,
                updated_at=datetime.utcnow().isoformat(),
                trace=trace
            )

            character_bible = _generate_character_bible(story_brief, selected_model=selected_model)
            trace.append({
                "stage": "character_writer",
                "summary": character_bible["summary"],
                "time": datetime.utcnow().isoformat()
            })

            _set_chat_task(
                task_id,
                project_id=project_id,
                status="running",
                current_stage="plot_writer",
                progress=55,
                updated_at=datetime.utcnow().isoformat(),
                trace=trace
            )

            plot_outline = _generate_plot_outline(story_brief, character_bible, selected_model=selected_model)
            trace.append({
                "stage": "plot_writer",
                "summary": plot_outline["summary"],
                "time": datetime.utcnow().isoformat()
            })

            _set_chat_task(
                task_id,
                project_id=project_id,
                status="reviewing",
                current_stage="reviewer",
                progress=75,
                updated_at=datetime.utcnow().isoformat(),
                trace=trace
            )

            review_report = _review_artifacts(story_brief, character_bible, plot_outline, selected_model=selected_model)
            trace.append({
                "stage": "reviewer",
                "summary": review_report["summary"],
                "time": datetime.utcnow().isoformat()
            })

            # 第一版：最多自动回修一次
            if review_report.get("rewrite_required"):
                _set_chat_task(
                    task_id,
                    project_id=project_id,
                    status="retrying",
                    current_stage="plot_writer",
                    progress=85,
                    updated_at=datetime.utcnow().isoformat(),
                    trace=trace
                )

                retry_meta = dict(meta)
                retry_meta["banned"] = ((meta.get("banned") or "") + "；请加强开头钩子、冲突推进和追更点").strip("；")
                retry_brief = _build_story_brief(message, retry_meta, mode, user_id, project_id=project_id)

                plot_outline = _generate_plot_outline(retry_brief, character_bible, selected_model=selected_model)
                trace.append({
                    "stage": "plot_writer_retry",
                    "summary": plot_outline["summary"],
                    "time": datetime.utcnow().isoformat()
                })

                review_report = _review_artifacts(retry_brief, character_bible, plot_outline, selected_model=selected_model)
                trace.append({
                    "stage": "reviewer_retry",
                    "summary": review_report["summary"],
                    "time": datetime.utcnow().isoformat()
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
                updated_at=datetime.utcnow().isoformat(),
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
                updated_at=datetime.utcnow().isoformat(),
                error=str(e),
                traceback=traceback.format_exc()
            )


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
        task_id=task_id,
        session_id=session_id,
        project_id=project_id,
        status="pending",
        current_stage="queued",
        progress=0,
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
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