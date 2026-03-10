from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, Response
from common import db
from models import ScriptModel, UserModel
from flask_login import login_required, current_user
from models import ChapterModel, CharacterModel
from datetime import datetime, timedelta
import logging
import re
from flask import current_app
import urllib.parse

dashboard = Blueprint('dashboard', __name__)

@dashboard.route('/')
@login_required
def index():
    logging.debug(f"访问仪表板，用户认证状态: {current_user.is_authenticated}")
    logging.debug(f"当前用户: {current_user.id if current_user.is_authenticated else '未登录'}")
    page = request.args.get('page', 1, type=int)
    per_page = 10
    scripts = ScriptModel.query.filter_by(user_id=current_user.id).order_by(ScriptModel.updated_at.desc()).paginate(page=page, per_page=per_page)
    return render_template('dashboard.html', scripts=scripts, email=current_user.email, timedelta=timedelta)

@dashboard.route('/script/new', methods=['GET', 'POST'])
@login_required
def new_script():
    if request.method == 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                script = ScriptModel(
                    title=request.form.get('title'),
                    content=request.form.get('content'),
                    word_count=request.form.get('word_count', type=int),
                    style_type=request.form.get('style_type'),
                    write_style=request.form.get('write_style', '无'),
                    has_branching=request.form.get('has_branching') == 'true',
                    genre=request.form.get('genre'),
                    background=request.form.get('background', ''),
                    user_id=current_user.id
                )
                db.session.add(script)
                db.session.commit()
                return jsonify({'success': True, 'message': '剧本创建成功', 'script_id': script.id})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)}), 500
        else:
            script = ScriptModel(
                title=request.form.get('title'),
                content=request.form.get('content'),
                word_count=request.form.get('word_count', type=int),
                style_type=request.form.get('style_type'),
                write_style=request.form.get('write_style', '无'),
                has_branching=request.form.get('has_branching') == 'true',
                genre=request.form.get('genre'),
                background=request.form.get('background', ''),
                user_id=current_user.id
            )
            db.session.add(script)
            db.session.commit()
            flash('剧本创建成功')
            return redirect(url_for('dashboard.index'))
    return render_template('script_form.html', script=None, active_tab='basic')

@dashboard.route('/script/<int:script_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_script(script_id):
    script = ScriptModel.query.get_or_404(script_id)
    
    # 检查权限
    if script.user_id != current_user.id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': '您没有权限编辑此剧本'}), 403
        flash('您没有权限编辑此剧本')
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        script.title = request.form.get('title')
        script.content = request.form.get('content')
        script.word_count = request.form.get('word_count', type=int)
        script.style_type = request.form.get('style_type')
        script.write_style = request.form.get('write_style')
        script.genre = request.form.get('genre')
        script.has_branching = request.form.get('has_branching') == 'true'
        script.background = request.form.get('background', '')
        script.updated_at = datetime.utcnow()
        db.session.commit()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # 获取当前标签页
            active_tab = request.form.get('active_tab', 'basic')
            return jsonify({
                'success': True,
                'message': '剧本更新成功'
            })
        flash('剧本更新成功')
        return redirect(url_for('dashboard.index'))
    
    # 获取当前激活的标签页
    active_tab = request.args.get('tab', 'basic')
    
    # 获取章节列表
    page = request.args.get('page', 1, type=int)
    chapters = ChapterModel.query.filter_by(script_id=script_id).order_by(ChapterModel.number).paginate(page=page, per_page=10)
    
    # 获取角色列表
    character_page = request.args.get('character_page', 1, type=int)
    characters = CharacterModel.query.filter_by(script_id=script_id).order_by(CharacterModel.name).paginate(page=character_page, per_page=10)
    
    return render_template('script_form.html', script=script, chapters=chapters, characters=characters, active_tab=active_tab)

@dashboard.route('/script/<int:script_id>/export_story_txt', methods=['GET'])
@login_required
def export_story_txt(script_id):
    script = ScriptModel.query.get_or_404(script_id)
    if script.user_id != current_user.id:
        flash('您没有权限导出此故事')
        return redirect(url_for('dashboard.index'))
    
    # 获取所有章节
    chapters = ChapterModel.query.filter_by(script_id=script_id).order_by(ChapterModel.number).all()
    
    # 创建导出内容
    content = f"《{script.title}》\n\n"
    
    # 添加章节内容
    for chapter in chapters:
        content += f"\n第{chapter.number}章 {chapter.title}\n\n"
        # 检查chapter_content是否存在且不为空
        if hasattr(chapter, 'chapter_content') and chapter.chapter_content:
            content += chapter.chapter_content + "\n"
        else:
            # 如果没有chapter_content字段或为空，尝试使用content字段
            content += getattr(chapter, 'content', '(章节内容为空)') + "\n"
    
    # 使用RFC 5987编码文件名，解决中文文件名问题
    safe_filename = urllib.parse.quote(f"{script.title}_故事内容.txt")
    
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        "Content-Type": "text/plain; charset=utf-8"
    }
    
    response = Response(
        content.encode('utf-8'),
        mimetype="text/plain; charset=utf-8",
        headers=headers
    )
    
    # 添加额外的下载触发标志
    response.headers["X-Download-Options"] = "noopen"
    response.headers["X-Content-Type-Options"] = "nosniff"
    
    return response

@dashboard.route('/script/<int:script_id>/export_script_txt', methods=['GET'])
@login_required
def export_script_txt(script_id):
    script = ScriptModel.query.get_or_404(script_id)
    if script.user_id != current_user.id:
        flash('您没有权限导出此剧本')
        return redirect(url_for('dashboard.index'))
    
    # 获取所有章节
    chapters = ChapterModel.query.filter_by(script_id=script_id).order_by(ChapterModel.number).all()
    
    # 获取所有角色
    characters = CharacterModel.query.filter_by(script_id=script_id).all()
    
    # 创建导出内容
    content = f"《{script.title}》剧本\n\n"
    
    # 添加角色列表
    if characters:
        content += "【角色表】\n\n"
        for character in characters:
            content += f"{character.name}: {character.gender}, {character.age}岁\n"
            if character.description:
                content += f"描述: {character.description}\n"
            content += "\n"
    
    # 添加章节内容
    for chapter in chapters:
        content += f"\n第{chapter.number}章 {chapter.title}\n\n"
        # 检查chapter_script是否存在且不为空
        if hasattr(chapter, 'chapter_script') and chapter.chapter_script:
            content += chapter.chapter_script + "\n"
        else:
            # 如果没有chapter_script字段或为空，添加提示
            content += "(章节剧本内容为空)\n"
    
    # 使用RFC 5987编码文件名，解决中文文件名问题
    safe_filename = urllib.parse.quote(f"{script.title}_剧本.txt")
    
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        "Content-Type": "text/plain; charset=utf-8"
    }
    
    response = Response(
        content.encode('utf-8'),
        mimetype="text/plain; charset=utf-8",
        headers=headers
    )
    
    # 添加额外的下载触发标志
    response.headers["X-Download-Options"] = "noopen"
    response.headers["X-Content-Type-Options"] = "nosniff"
    
    return response

@dashboard.route('/script/<int:script_id>/delete', methods=['POST'])
@login_required
def delete_script(script_id):
    script = ScriptModel.query.get_or_404(script_id)
    if script.user_id != current_user.id:
        flash('您没有权限删除此剧本')
        return redirect(url_for('dashboard.index'))
    
    db.session.delete(script)
    db.session.commit()
    flash('剧本删除成功')
    return redirect(url_for('dashboard.index'))

@dashboard.route('/script/<int:script_id>/update_field', methods=['POST'])
@login_required
def update_field(script_id):
    script = ScriptModel.query.get_or_404(script_id)
    if script.user_id != current_user.id:
        return jsonify({'success': False, 'message': '您没有权限更新此剧本'}), 403
    
    field = request.args.get('field')
    if not field:
        return jsonify({'success': False, 'message': '未指定要更新的字段'}), 400
    
    # 检查字段是否存在
    if not hasattr(script, field):
        return jsonify({'success': False, 'message': f'字段 {field} 不存在'}), 400
    
    # 获取字段值
    field_value = request.form.get(field, '')
    
    # 动态设置字段值
    setattr(script, field, field_value)
    script.updated_at = datetime.utcnow()
    db.session.commit()
   
    return jsonify({
        'success': True, 
        'message': f'保存成功'
    }) 