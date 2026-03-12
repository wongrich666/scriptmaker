"""
github地址  https://github.com/wongrich666/scriptmaker.git
ctrl K提交，ctrl shift K上传
网页运行中打开 http://192.168.1.39:60002/api/chat/task/任务id 可以查看运行的怎么样了
打开 http://192.168.1.39:60002/api/chat/project/36或者其他数字/artifacts 查看是否有四个内容
"""

"""
使用终端上传的方法：
1. 进入项目目录（如果还没进入）
cd C:\\Users\\Administrator\\PycharmProjects\\scriptMaker

2. 确认修改的文件已添加到暂存区（如果没加）
git add .

3. 提交代码（对应 Ctrl+K）
git commit -m "本次修改的说明，比如：优化脚本生成逻辑"

4. 推送到 GitHub（对应 Ctrl+Shift+K）
git push origin main
"""

"""
1. 更新 GitHub 本地仓库
进入你的 Git 仓库目录，确认当前的修改（文件名变更等）：
git status
你应该会看到文件名变化（例如 api.py 被重命名为 chat_api.py）以及任何其他的修改。

2. 提交本地修改
首先，添加所有更改到暂存区：
git add -A
然后，提交更改：
git commit -m "Renamed api.py to chat_api.py and updated relevant changes"

3. 推送到 GitHub
将本地提交推送到 GitHub 上：
git push origin main
（如果你使用的是其他分支，替换 main 为相应的分支名称。）
"""

from werkzeug.exceptions import HTTPException
from common import create_app, init_login, db
from models import init_models
from auth import auth
from dashboard import dashboard
from chapters import chapters
from characters import characters
from chat_api import api
from branches import branches
from menu import menu
from chat import chat
from flask import redirect, url_for, render_template
from flask_login import current_user, login_required
import logging
import sys
import os
import chat_api

print("chat_api file =", chat_api.__file__)
print("api blueprint deferred_functions =", len(api.deferred_functions))

# 创建日志目录
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'app.log'), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

def create_app_with_blueprints():
    try:
        app = create_app()
        login_manager = init_login(app)

        # 注册蓝图
        app.register_blueprint(auth, url_prefix='/auth')
        app.register_blueprint(dashboard, url_prefix='/dashboard')
        app.register_blueprint(chapters, url_prefix='/chapters')
        app.register_blueprint(characters, url_prefix='/characters')
        app.register_blueprint(api, url_prefix='/api')
        app.register_blueprint(branches, url_prefix='/chapters')
        app.register_blueprint(menu, url_prefix='/menu')
        app.register_blueprint(chat)   # 新增聊天页主入口

        # 根路由：已登录直接去聊天页
        @app.route('/')
        def index():
            if current_user.is_authenticated:
                return redirect(url_for('chat.index'))
            return redirect(url_for('auth.login'))

        # 测试路由
        @app.route('/test')
        def test_route():
            logging.debug("主应用测试路由被访问")
            return render_template('test.html')

        # 字体测试路由
        @app.route('/test-font')
        def test_font_route():
            logging.debug("字体测试页面被访问")
            return render_template('test_font.html')

        # 思维导图路由
        @app.route('/mindmap')
        @login_required
        def mindmap():
            return render_template('mindmap.html')

        # 初始化模型
        UserModel, _, _, _ = init_models()

        @login_manager.user_loader
        def load_user(user_id):
            try:
                user = UserModel.query.get(int(user_id))
                return user
            except Exception as e:
                logging.error(f"加载用户失败: {str(e)}")
                return None

        # 创建数据库表
        with app.app_context():
            db.create_all()

        # 错误处理器
        @app.errorhandler(Exception)
        def handle_exception(e):
            import traceback
            from flask import jsonify, request, render_template_string

            # 先放行 404 / 405 / 403 等 HTTP 错误
            if isinstance(e, HTTPException):
                if request.path.startswith('/api/'):
                    return jsonify({
                        'success': False,
                        'error': e.description,
                        'code': e.code
                    }), e.code
                return e

            error_traceback = traceback.format_exc()
            logging.error(f"发生错误: {str(e)}\n{error_traceback}")

            # API 请求返回 JSON
            if request.path.startswith('/api/'):
                return jsonify({
                    'success': False,
                    'error': str(e),
                    'traceback': error_traceback
                }), 500

            # 普通页面返回 HTML 错误页
            return render_template_string('''
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">
                    <title>服务器错误</title>
                    <style>
                        body { font-family: monospace; margin: 20px; background: #f5f5f5; }
                        h1 { color: #d32f2f; }
                        .error-box { background: white; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                        pre { background: #f5f5f5; padding: 15px; border-left: 4px solid #d32f2f; overflow-x: auto; white-space: pre-wrap; }
                    </style>
                </head>
                <body>
                    <div class="error-box">
                        <h1>服务器内部错误</h1>
                        <h2>错误信息:</h2>
                        <p><strong>{{ error }}</strong></p>
                        <h2>完整堆栈跟踪:</h2>
                        <pre>{{ traceback }}</pre>
                    </div>
                </body>
                </html>
            ''', error=str(e), traceback=error_traceback), 500

        return app

    except Exception as e:
        logging.error(f"应用初始化失败: {str(e)}")
        raise


app = create_app_with_blueprints()
print(app.url_map)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=60002, debug=False)