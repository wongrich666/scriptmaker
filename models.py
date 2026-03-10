from flask_login import UserMixin
from common import db
import hashlib
from datetime import datetime

# 定义基础模型类
class UserModel(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    # 微信用户相关字段
    wx_openid = db.Column(db.String(50), unique=True, nullable=True)
    wx_nickname = db.Column(db.String(50), nullable=True)
    wx_avatar = db.Column(db.String(255), nullable=True)
    register_type = db.Column(db.String(10), default='email')  # email, wechat
    scripts = db.relationship('ScriptModel', backref='user', lazy=True)

    def __init__(self, email):
        self.email = email

    def set_password(self, password):
        self.password_hash = hashlib.sha256(password.encode()).hexdigest()

    def check_password(self, password):
        return self.password_hash == hashlib.sha256(password.encode()).hexdigest()

    def get_id(self):
        return str(self.id)

class ScriptModel(db.Model):
    __tablename__ = 'scripts'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    background = db.Column(db.Text, default='')
    characters = db.Column(db.Text, default='')
    relationships = db.Column(db.Text, default='')
    knowledge = db.Column(db.Text, default='')
    style = db.Column(db.Text, default='')
    write_style = db.Column(db.Text, default='')
    outline = db.Column(db.Text, default='')
    word_count = db.Column(db.Integer, default=0)
    style_type = db.Column(db.String(20), default='2d_realistic')  # 2d_realistic, 2d_cartoon, 3d_realistic, 3d_cartoon
    has_branching = db.Column(db.Boolean, default=False)  # 是否有情节分支
    mind_map = db.Column(db.Text, default='')
    genre = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    chapters = db.relationship('ChapterModel', backref='script', lazy=True, cascade='all, delete-orphan')
    characters_list = db.relationship('CharacterModel', backref='script', lazy=True, cascade='all, delete-orphan')

class CharacterModel(db.Model):
    __tablename__ = 'characters'
    id = db.Column(db.Integer, primary_key=True)
    script_id = db.Column(db.Integer, db.ForeignKey('scripts.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    gender = db.Column(db.String(10))  # 男/女/其他
    age = db.Column(db.Integer)
    description = db.Column(db.Text)  # 个人信息
    personality = db.Column(db.Text)  # 性格特点
    background = db.Column(db.Text)   # 背景故事
    relationships = db.Column(db.Text) # 与其他角色的关系
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

class ChapterModel(db.Model):
    __tablename__ = 'chapters'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, nullable=False) # 章节编号
    title = db.Column(db.String(200), nullable=False) # 章节标题
    chapter_outline = db.Column(db.Text, nullable=False) # 章节大纲
    chapter_content = db.Column(db.Text) # 章节内容
    chapter_script = db.Column(db.Text) # 章节脚本内容
    script_id = db.Column(db.Integer, db.ForeignKey('scripts.id'), nullable=False)
    previous_id = db.Column(db.Integer, db.ForeignKey('chapters.id'), nullable=True) # 上一章节ID
    next_id = db.Column(db.Integer, db.ForeignKey('chapters.id'), nullable=True) # 下一章节ID
    
    previous = db.relationship('ChapterModel', remote_side=[id], foreign_keys=[previous_id], backref=db.backref('next_chapter', uselist=False))
    next = db.relationship('ChapterModel', remote_side=[id], foreign_keys=[next_id], backref=db.backref('previous_chapter', uselist=False))

# 工厂函数
def init_models():
    return UserModel, ScriptModel, ChapterModel, CharacterModel 