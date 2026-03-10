from common import create_app, init_login, db
from models import init_models
from auth import auth
from dashboard import dashboard
from chapters import chapters
from characters import characters
from api import api
from branches import branches
from menu import menu
from flask import redirect, url_for, render_template
from flask_login import current_user, login_required
import logging
import sys
import os

# 创建日志目录
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'app.log')),
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
        
        # 添加根路由
        @app.route('/')
        def index():
            if current_user.is_authenticated:
                return redirect(url_for('dashboard.index'))
            return redirect(url_for('auth.login'))
            
        # 添加测试路由
        @app.route('/test')
        def test_route():
            logging.debug("主应用测试路由被访问")
            return render_template('test.html')
        
        # 添加字体测试路由
        @app.route('/test-font')
        def test_font_route():
            logging.debug("字体测试页面被访问")
            return render_template('test_font.html')
        
        # 添加新路由
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
        
        # 添加错误处理器，显示详细错误信息
        @app.errorhandler(Exception)
        def handle_exception(e):
            import traceback
            from flask import jsonify, request
            
            # 记录完整错误信息到日志
            error_traceback = traceback.format_exc()
            logging.error(f"发生错误: {str(e)}\n{error_traceback}")
            
            # 如果是API请求，返回JSON格式错误
            if request.path.startswith('/api/'):
                return jsonify({
                    'success': False,
                    'error': str(e),
                    'traceback': error_traceback
                }), 500
            
            # 返回HTML格式的错误页面，显示完整错误信息
            from flask import render_template_string
            return render_template_string('''
                <!DOCTYPE html>
                <html>
                <head>
                    <title>服务器错误</title>
                    <style>
                        body { font-family: monospace; margin: 20px; background: #f5f5f5; }
                        h1 { color: #d32f2f; }
                        .error-box { background: white; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                        pre { background: #f5f5f5; padding: 15px; border-left: 4px solid #d32f2f; overflow-x: auto; }
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

if __name__ == '__main__':
    try:
        # 根据环境变量决定是否启用调试模式
        debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
        app.run(debug=debug_mode, port=60002, host="0.0.0.0")
    except Exception as e:
        logging.error(f"应用启动失败: {str(e)}")
        raise
