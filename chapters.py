from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from common import db
from models import ChapterModel, ScriptModel

chapters = Blueprint('chapters', __name__)

@chapters.route('/script/<int:script_id>/chapters')
@login_required
def script_chapters(script_id):
    script = ScriptModel.query.get_or_404(script_id)
    if script.user_id != current_user.id:
        flash('您没有权限访问此剧本')
        return redirect(url_for('dashboard.index'))
    
    page = request.args.get('page', 1, type=int)
    active_tab = request.args.get('tab', 'chapters')
    per_page = 10
    chapters = ChapterModel.query.filter_by(script_id=script_id).order_by(ChapterModel.number).paginate(page=page, per_page=per_page)
    return render_template('script_form.html', script=script, chapters=chapters, active_tab=active_tab)


@chapters.route('/chapters/<int:chapter_id>', methods=['GET'])
@login_required
def get_chapter(chapter_id):
    chapter = ChapterModel.query.get_or_404(chapter_id)
    if chapter.script.user_id != current_user.id:
        return jsonify({'error': '没有权限'}), 403
    return jsonify({
        'id': chapter.id,
        'number': chapter.number,
        'title': chapter.title,
        'content': chapter.content,
        'status': chapter.status
    })

@chapters.route('/chapters/<int:chapter_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_chapter(chapter_id):
    chapter = ChapterModel.query.get_or_404(chapter_id)
    if chapter.script.user_id != current_user.id:
        flash('您没有权限编辑此章节')
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        chapter.number = request.form.get('number', type=int)
        chapter.title = request.form.get('title')
        chapter.chapter_outline = request.form.get('chapter_outline')
        chapter.chapter_content = request.form.get('chapter_content')
        chapter.chapter_script = request.form.get('chapter_script')
        previous_id = request.form.get('previous_id', type=int)
        next_id = request.form.get('next_id', type=int)
        
        if previous_id and previous_id != 0:
            chapter.previous_id = previous_id
        if next_id and next_id != 0:
            chapter.next_id = next_id
        db.session.commit()
        return jsonify({'success': True, 'message': '章节更新成功'})
    
    return render_template('chapter_form.html', chapter=chapter, script=chapter.script)

@chapters.route('/chapters/<int:chapter_id>', methods=['DELETE'])
@login_required
def delete_chapter(chapter_id):
    chapter = ChapterModel.query.get_or_404(chapter_id)
    if chapter.script.user_id != current_user.id:
        return jsonify({'success': False, 'message': '没有权限删除此章节'}), 403
    
    db.session.delete(chapter)
    db.session.commit()
    return jsonify({'success': True}) 