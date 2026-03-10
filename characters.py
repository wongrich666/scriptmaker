from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from models import CharacterModel, ScriptModel
from common import db
from datetime import datetime

characters = Blueprint('characters', __name__)

@characters.route('/<int:script_id>/character/<int:character_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_character(script_id, character_id):
    script = ScriptModel.query.get_or_404(script_id)
    character = CharacterModel.query.get_or_404(character_id)
    
    # 检查权限
    if script.user_id != current_user.id or character.script_id != script_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': '您没有权限编辑此角色'
            }), 403
        flash('您没有权限编辑此角色')
        return redirect(url_for('dashboard.edit_script', script_id=script_id, tab='characters'))
    
    if request.method == 'POST':
        character.name = request.form.get('name')
        character.gender = request.form.get('gender')
        character.age = request.form.get('age', type=int)
        character.description = request.form.get('description')
        character.personality = request.form.get('personality')
        character.relationships = request.form.get('relationships')
        character.background = request.form.get('background')
        character.updated_at = datetime.utcnow()
        db.session.commit()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'message': '角色更新成功'
            })
        flash('角色更新成功')
        return redirect(url_for('dashboard.edit_script', script_id=script_id, tab='characters'))
    
    return render_template('character_form.html', script=script, character=character)

@characters.route('/characters/<int:script_id>/character/<int:character_id>/delete', methods=['POST'])
@login_required
def delete_character(script_id, character_id):
    
    try:
        character = CharacterModel.query.get_or_404(character_id)
        script = ScriptModel.query.get_or_404(script_id)
        
        if character.script_id != script_id:
            return jsonify({
                'success': False,
                'message': '角色不属于该剧本'
            }), 403
        
        if script.user_id != current_user.id:
            return jsonify({
                'success': False,
                'message': '您没有权限删除此角色'
            }), 403
        
        current_page = request.form.get('character_page', 1, type=int)
        
        db.session.delete(character)
        db.session.commit()
        
        # 检查当前页是否还有角色
        remaining_characters = CharacterModel.query.filter_by(script_id=script_id).count()
        
        # 如果当前页没有角色了，且不是第一页，则返回上一页
        if current_page > 1 and remaining_characters <= (current_page - 1) * 10:
            current_page -= 1
        
        redirect_url = url_for('dashboard.edit_script', script_id=script_id, tab='characters', character_page=current_page)
        
        return jsonify({
            'success': True,
            'message': '角色删除成功',
            'url': redirect_url
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'删除角色失败: {str(e)}'
        }), 500
