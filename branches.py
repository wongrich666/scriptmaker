from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from models import ScriptModel, ChapterModel
import logging
import traceback
import json

# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

branches = Blueprint('branches', __name__)

@branches.route('/branches/<int:script_id>')
@login_required
def show_branches(script_id):
    try:
        logger.debug("="*50)
        logger.debug("开始处理分支管理页面请求")
        logger.debug(f"请求路径: {request.path}")
        logger.debug(f"请求方法: {request.method}")
        logger.debug(f"当前用户ID: {current_user.id}")
        logger.debug(f"请求的剧本ID: {script_id}")
        
        script = ScriptModel.query.get_or_404(script_id)
        logger.debug(f"找到剧本: {script.id}, 所有者: {script.user_id}")
        
        # 检查用户权限
        if script.user_id != current_user.id:
            logger.warning(f"用户 {current_user.id} 尝试访问不属于自己的剧本 {script_id}")
            return "无权访问此剧本", 403
        
        # 获取所有章节
        chapters = ChapterModel.query.filter_by(script_id=script_id).all()
        logger.debug(f"获取到 {len(chapters)} 个章节")
        
        # 准备章节JSON数据
        chapters_json = []
        for chapter in chapters:
            chapters_json.append({
                'id': chapter.id,
                'number': chapter.number,
                'title': chapter.title,
                'previous_id': chapter.previous_id,
                'next_id': chapter.next_id
            })
        
        chapters_json_str = json.dumps(chapters_json)
        
        logger.debug("准备渲染模板")
        return render_template('branches.html', script=script, chapters=chapters, chapters_json=chapters_json_str)
        
    except Exception as e:
        logger.error(f"处理请求时出错: {str(e)}")
        logger.error(traceback.format_exc())
        return f"服务器错误: {str(e)}", 500

@branches.route('/branches/<int:script_id>/save', methods=['POST'])
@login_required
def save_branches(script_id):
    try:
        logger.debug("="*50)
        logger.debug("开始处理保存分支数据请求")
        logger.debug(f"请求路径: {request.path}")
        logger.debug(f"请求方法: {request.method}")
        logger.debug(f"当前用户ID: {current_user.id}")
        logger.debug(f"请求的剧本ID: {script_id}")
        
        data = request.get_json()
        logger.debug(f"接收到的数据: {data}")
        
        # 验证数据
        if not data or 'connections' not in data:
            logger.error("无效的请求数据")
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400
        
        # 更新章节关系
        for conn in data['connections']:
            chapter = ChapterModel.query.get(conn['id'])
            if chapter:
                chapter.previous_id = conn.get('previous_id')
                chapter.next_id = conn.get('next_id')
                logger.debug(f"更新章节 {chapter.id} 的关系: previous_id={chapter.previous_id}, next_id={chapter.next_id}")
        
        current_app.db.session.commit()
        logger.info(f"成功保存剧本 {script_id} 的分支数据")
        return jsonify({'success': True, 'message': '分支数据保存成功'})
        
    except Exception as e:
        current_app.db.session.rollback()
        logger.error(f"保存分支数据时出错: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'保存失败: {str(e)}'}), 500 