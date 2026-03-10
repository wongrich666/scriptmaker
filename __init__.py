from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
import logging
import os

# 创建全局数据库实例
db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # 配置日志
    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)
    
    # 初始化数据库
    db.init_app(app)
    
    # 初始化登录管理器
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)
    
    # 注册蓝图
    from auth import auth as auth_blueprint
    from dashboard import dashboard as dashboard_blueprint
    from chapters import chapters as chapters_blueprint
    from branches import branches as branches_blueprint
    
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(dashboard_blueprint)
    app.register_blueprint(chapters_blueprint, url_prefix='/chapters')
    app.register_blueprint(branches_blueprint, url_prefix='/chapters')
    
    return app

def init_login(app):
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    return login_manager 