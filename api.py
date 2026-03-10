from flask import Blueprint, request, jsonify, session
from flask_login import login_required, current_user
import os
import json
import re
import requests
import time
from urllib.parse import urlparse
from models import CharacterModel, ChapterModel, ScriptModel, db

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