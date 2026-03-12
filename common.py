from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import logging
import os
from dotenv import load_dotenv

load_dotenv()

# 创建全局数据库实例
db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # 禁用模板缓存 - 开发环境
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    
    # 禁用静态文件缓存
    app.config['STATIC_FOLDER'] = 'static'
    
    # 启用详细错误信息显示（总是显示，便于调试）
    app.config['PROPAGATE_EXCEPTIONS'] = True
    # 注意：DEBUG模式在生产环境应设为False，但错误处理器会始终显示详细信息
    app.config['DEBUG'] = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    app.config['TRAP_HTTP_EXCEPTIONS'] = True
    
    logging.basicConfig(level=logging.DEBUG)

    # JSON 直接输出中文，不要变成 \u4e2d\u6587
    app.config['JSON_AS_ASCII'] = False
    app.config['JSON_SORT_KEYS'] = False

    try:
        # Flask 2.3+
        app.json.ensure_ascii = False
        app.json.sort_keys = False
    except Exception:
        pass

    # 初始化数据库
    db.init_app(app)
    
    return app

def init_login(app):
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    return login_manager 