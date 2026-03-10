from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from common import db
from models import UserModel
import hashlib
from email_validator import validate_email, EmailNotValidError
import logging
import re
import requests
import os
import time
import uuid
import json
from urllib.parse import quote
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
auth = Blueprint('auth', __name__)
# 强制从.env文件加载环境变量，覆盖已存在的环境变量
load_dotenv(override=True)
# 二维码状态持久化到数据库
class WechatQrcode(db.Model):
    __tablename__ = 'wechat_qrcode'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    scene_str = db.Column(db.String(100), unique=True, nullable=False)
    scanned = db.Column(db.Boolean, default=False)
    openid = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    expires_at = db.Column(db.DateTime)
    
    @classmethod
    def create(cls, scene_str, expires_seconds=600):
        """创建新的二维码状态记录"""
        try:
            qrcode = cls(
                scene_str=scene_str,
                scanned=False,
                openid=None,
                created_at=datetime.now(),
                expires_at=datetime.now() + timedelta(seconds=expires_seconds)
            )
            db.session.add(qrcode)
            db.session.commit()
            return qrcode
        except IntegrityError:
            db.session.rollback()
            # 如果已存在，则更新它
            qrcode = cls.query.filter_by(scene_str=scene_str).first()
            if qrcode:
                qrcode.scanned = False
                qrcode.openid = None
                qrcode.created_at = datetime.now()
                qrcode.expires_at = datetime.now() + timedelta(seconds=expires_seconds)
                db.session.commit()
                return qrcode
            return None
    
    @classmethod
    def get_by_scene_str(cls, scene_str):
        """根据场景值获取二维码状态"""
        return cls.query.filter_by(scene_str=scene_str).first()
    
    @classmethod
    def update_scanned(cls, scene_str, openid):
        """更新为已扫描状态"""
        logging.debug(f"尝试更新二维码状态: scene_str={scene_str}, openid={openid}")
        
        if not scene_str or not openid:
            logging.error(f"更新二维码状态失败: 参数无效 scene_str={scene_str}, openid={openid}")
            return False
        
        try:
            qrcode = cls.get_by_scene_str(scene_str)
            if qrcode:
                logging.debug(f"找到二维码记录: id={qrcode.id}, scene_str={qrcode.scene_str}, 当前状态: scanned={qrcode.scanned}")
                qrcode.scanned = True
                qrcode.openid = openid
                db.session.commit()
                logging.debug(f"二维码状态更新成功: scene_str={scene_str}")
                return True
            else:
                logging.warning(f"更新二维码状态失败: 找不到记录 scene_str={scene_str}")
                
                # 尝试创建新记录
                try:
                    logging.debug(f"尝试创建新的二维码记录: scene_str={scene_str}")
                    new_qrcode = cls(
                        scene_str=scene_str,
                        scanned=True,
                        openid=openid,
                        created_at=datetime.now(),
                        expires_at=datetime.now() + timedelta(minutes=10)
                    )
                    db.session.add(new_qrcode)
                    db.session.commit()
                    logging.debug(f"创建新二维码记录成功: scene_str={scene_str}")
                    return True
                except Exception as e:
                    db.session.rollback()
                    logging.error(f"创建新二维码记录失败: {e}", exc_info=True)
                    return False
        except Exception as e:
            db.session.rollback()
            logging.error(f"更新二维码状态异常: {e}", exc_info=True)
            return False
    
    def is_expired(self):
        """检查是否已过期"""
        return datetime.now() > self.expires_at if self.expires_at else True

# 获取微信接口的access_token
def get_wechat_access_token():
    """获取微信公众号的access_token"""
    # 实际应用中应从配置文件或环境变量获取
    appid = os.getenv("WECHAT_APPID")
    appsecret = os.getenv("WECHAT_APPSECRET")
    
    # 如果已经有缓存的access_token且未过期，直接返回
    if hasattr(get_wechat_access_token, "token_info"):
        token_info = get_wechat_access_token.token_info
        if token_info.get("expires_time", 0) > time.time():
            return token_info.get("access_token")
    
    # 否则重新获取
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={appsecret}"
    try:
        response = requests.get(url)
        result = response.json()
        logging.debug(f"获取access_token响应: {result}")
        
        if "access_token" in result:
            # 保存token和过期时间
            get_wechat_access_token.token_info = {
                "access_token": result["access_token"],
                "expires_time": time.time() + result["expires_in"] - 200  # 提前200秒过期
            }
            return result["access_token"]
        else:
            logging.error(f"获取access_token失败: {result}")
    except Exception as e:
        logging.error(f"获取微信access_token失败: {e}")
    
    return None

# 生成临时二维码
def generate_temp_qrcode(scene_str, expire_seconds=600):
    """
    生成临时二维码
    :param scene_str: 场景值字符串
    :param expire_seconds: 过期时间，单位秒，默认10分钟
    :return: 二维码URL或None
    """
    access_token = get_wechat_access_token()
    if not access_token:
        logging.error("无法获取微信access_token")
        return None
    
    url = f"https://api.weixin.qq.com/cgi-bin/qrcode/create?access_token={access_token}"
    data = {
        "expire_seconds": expire_seconds,
        "action_name": "QR_STR_SCENE",
        "action_info": {"scene": {"scene_str": scene_str}}
    }
    
    try:
        logging.debug(f"请求微信二维码API，参数: {data}")
        response = requests.post(url, data=json.dumps(data))
        result = response.json()
        logging.debug(f"微信二维码API响应: {result}")
        
        if "ticket" in result:
            # 创建二维码状态记录
            WechatQrcode.create(scene_str, expire_seconds)
            
            # 返回二维码URL
            ticket = result["ticket"]
            # 注意：票据需要进行URL编码
            encoded_ticket = quote(ticket)
            qrcode_url = f"https://mp.weixin.qq.com/cgi-bin/showqrcode?ticket={encoded_ticket}"
            logging.debug(f"生成二维码URL: {qrcode_url}")
            return qrcode_url
        else:
            logging.error(f"微信生成二维码失败: {result}")
    except Exception as e:
        logging.error(f"生成微信临时二维码失败: {e}")
    
    return None

# 添加手机号验证函数
def is_valid_phone(phone):
    # 验证中国大陆手机号格式（11位数字，以1开头）
    pattern = r'^1[3-9]\d{9}$'
    return bool(re.match(pattern, phone))

# 验证用户名（可以是邮箱或手机号）
def validate_username(username):
    # 先尝试验证为手机号
    if is_valid_phone(username):
        return True
    
    # 再尝试验证为邮箱
    try:
        validate_email(username)
        return True
    except EmailNotValidError:
        return False

@auth.route('/')
def index():
    logging.debug(f"访问认证根路径，用户认证状态: {current_user.is_authenticated}")
    if current_user.is_authenticated:
        logging.debug("用户已登录，重定向到聊天主页")
        return redirect(url_for('chat.index'))
    logging.debug("用户未登录，重定向到登录页面")
    return redirect(url_for('auth.login'))

@auth.route('/login', methods=['GET', 'POST'])
def login():
    logging.debug(f"访问登录页面，用户认证状态: {current_user.is_authenticated}")
    if current_user.is_authenticated:
        logging.debug("用户已登录，重定向到聊天主页")
        return redirect(url_for('chat.index'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not validate_username(email):
            flash('无效的邮箱或手机号格式')
            return redirect(url_for('auth.login'))

        user = UserModel.query.filter_by(email=email).first()
        if user and user.password_hash == hashlib.sha256(password.encode()).hexdigest():
            logging.debug(f"用户 {email} 登录成功")
            session.clear()
            login_user(user)
            logging.debug(f"用户 {email} 已登录，重定向到聊天主页")
            return redirect(url_for('chat.index'))
        else:
            flash('用户名或密码错误')

    return render_template('login.html')

@auth.route('/register', methods=['GET', 'POST'])
def register():
    logging.debug(f"访问注册页面，用户认证状态: {current_user.is_authenticated}")
    if current_user.is_authenticated:
        logging.debug("用户已登录，重定向到聊天主页")
        return redirect(url_for('chat.index'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not validate_username(email):
            flash('无效的邮箱或手机号格式')
            return redirect(url_for('auth.register'))

        if UserModel.query.filter_by(email=email).first():
            flash('该用户名已被注册')
            return redirect(url_for('auth.register'))

        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        new_user = UserModel(email)
        new_user.password_hash = hashed_password
        db.session.add(new_user)
        db.session.commit()

        logging.debug(f"用户 {email} 注册成功，准备登录")
        session.clear()
        login_user(new_user)
        logging.debug(f"用户 {email} 已登录，准备重定向到聊天主页")
        flash('注册成功')
        return redirect(url_for('chat.index'))

    return render_template('register.html')

@auth.route('/logout')
@login_required
def logout():
    logging.debug(f"用户登出")
    # 清除所有会话数据
    session.clear()
    logout_user()
    return redirect(url_for('auth.index'))

@auth.route('/check_wechat_scan', methods=['GET'])
def check_wechat_scan():
    """
    检查微信扫码状态的API
    """
    scene_str = request.args.get('scene_str', '')
    logging.debug(f"检查扫码状态: scene_str={scene_str}")
    
    if not scene_str:
        logging.warning("缺少scene_str参数")
        return jsonify({
            'scanned': False,
            'registered': False,
            'message': '缺少scene_str参数'
        })
    
    # 从数据库中查询二维码状态
    qrcode = WechatQrcode.get_by_scene_str(scene_str)
    
    if not qrcode:
        logging.warning(f"找不到scene_str={scene_str}的二维码记录")
        return jsonify({
            'scanned': False,
            'registered': False,
            'message': '无效的二维码'
        })
    
    # 记录当前二维码状态
    logging.debug(f"二维码状态: scene_str={scene_str}, scanned={qrcode.scanned}, " +
                  f"openid={qrcode.openid}, created_at={qrcode.created_at}, " +
                  f"expires_at={qrcode.expires_at}")
    
    # 检查是否过期
    if qrcode.is_expired():
        logging.debug(f"二维码已过期: scene_str={scene_str}")
        return jsonify({
            'scanned': False,
            'registered': False,
            'message': '二维码已过期'
        })
    
    # 检查是否已扫描并获取到openid
    if qrcode.scanned and qrcode.openid:
        openid = qrcode.openid
        logging.debug(f"二维码已扫描: scene_str={scene_str}, openid={openid}")
        
        # 查找此openid对应的用户
        user = UserModel.query.filter_by(wx_openid=openid).first()
        
        # 如果用户存在，返回用户已注册，可以登录
        if user:
            logging.debug(f"找到用户: email={user.email}, wx_openid={user.wx_openid}")
            # 自动登录该用户
            login_user(user)
            return jsonify({
                'scanned': True,
                'registered': True,
                'redirect_url': url_for('chat.index')  # 直接跳转到菜单页面
            })
        else:
            logging.debug(f"未找到用户: openid={openid}，尝试自动创建")
            
            try:
                # 自动创建微信用户
                email = f"wx_{openid}@user.com"
                new_user = UserModel(email)
                new_user.wx_openid = openid
                new_user.wx_nickname = f"微信用户_{openid[:6]}"
                new_user.wx_avatar = ''
                new_user.register_type = 'wechat'
                
                # 生成随机密码
                import random, string
                random_password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
                new_user.password_hash = hashlib.sha256(random_password.encode()).hexdigest()
                
                db.session.add(new_user)
                db.session.commit()
                
                # 自动登录
                login_user(new_user)
                logging.debug(f"自动创建并登录用户成功: {email}")
                
                return jsonify({
                    'scanned': True,
                    'registered': True,
                    'message': '注册成功',
                    'redirect_url': url_for('chat.index')  # 直接跳转到菜单页面
                })
            except Exception as e:
                logging.error(f"自动创建用户失败: {e}", exc_info=True)
                return jsonify({
                    'scanned': True,
                    'registered': False,
                    'message': f'创建用户失败: {str(e)}'
                })
    
    # 未扫描，继续等待
    return jsonify({
        'scanned': qrcode.scanned,
        'registered': False
    })

@auth.route('/wechat_qrcode/<action>', methods=['GET'])
def wechat_qrcode(action):
    """
    生成微信临时二维码
    :param action: 'login' 或 'register'
    """
    # 生成唯一的场景值
    scene_str = f"{action}_{uuid.uuid4().hex}"
    logging.debug(f"生成场景值: {scene_str}")
    
    # 生成临时二维码，有效期10分钟
    qrcode_url = generate_temp_qrcode(scene_str, 600)
    
    if qrcode_url:
        response = jsonify({
            'success': True,
            'qrcode_url': qrcode_url,
            'scene_str': scene_str
        })
        # 添加CORS头，允许来自任何源的请求（在开发环境中使用）
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    else:
        return jsonify({
            'success': False,
            'message': '生成二维码失败，请检查日志'
        })

@auth.route('/wechat_register_callback', methods=['GET', 'POST'])
def wechat_register_callback():
    """
    微信扫码注册回调处理
    """
    # 实际应用中，微信会回调这个地址，带上授权码
    code = request.args.get('code', '')
    state = request.args.get('state', '')
    
    if not code:
        flash('微信授权失败，请重试')
        return redirect(url_for('auth.register'))
    
    # 使用code获取微信访问令牌和用户信息
    # 这里需要实现与微信API的交互
    
    # 模拟获取微信用户信息
    # 实际应用中，应通过微信API获取真实信息
    wx_user_info = {
        'openid': 'sample_openid',
        'nickname': '微信用户',
        'headimgurl': '',
    }
    
    # 检查该微信账号是否已注册
    user = UserModel.query.filter_by(wx_openid=wx_user_info['openid']).first()
    
    if user:
        # 微信用户已存在，直接登录
        login_user(user)
        flash('微信账号登录成功')
        return redirect(url_for('chat.index'))
    else:
        # 创建新用户（使用微信信息）
        new_user = UserModel(f"wx_{wx_user_info['openid']}@wechat.user")
        new_user.wx_openid = wx_user_info['openid']
        new_user.wx_nickname = wx_user_info.get('nickname', '')
        new_user.wx_avatar = wx_user_info.get('headimgurl', '')
        new_user.register_type = 'wechat'
        # 生成随机密码，用户后续可更改
        import random, string
        random_password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        new_user.password_hash = hashlib.sha256(random_password.encode()).hexdigest()
        
        db.session.add(new_user)
        db.session.commit()
        
        # 注册成功后自动登录
        login_user(new_user)
        flash('微信注册成功')
        return redirect(url_for('chat.index'))

def extract_scene_str(event_key):
    """
    从微信事件中提取场景值字符串
    处理不同格式的场景值
    """
    if not event_key:
        return None
    
    # 去除可能的前缀
    scene_str = event_key
    
    # 处理关注事件的场景值前缀 qrscene_
    if scene_str.startswith('qrscene_'):
        scene_str = scene_str[8:]
    
    logging.debug(f"提取场景值: 原始值={event_key}, 处理后={scene_str}")
    return scene_str

@auth.route('/wechat_callback', methods=['GET', 'POST'])
def wechat_callback():
    """
    处理微信公众号推送的消息和事件
    这个接口需要在微信公众平台配置为服务器地址
    """
    # 直接写入文件日志，确保记录请求
    with open('logs/wechat_callback.log', 'a', encoding='utf-8') as f:
        f.write(f"\n----- 新请求 {datetime.now()} -----\n")
        f.write(f"请求方法: {request.method}\n")
        f.write(f"请求参数: {request.args}\n")
        if request.method == 'POST':
            f.write(f"请求数据: {request.data}\n")
        
    # 微信服务器会发送XML格式的消息
    if request.method == 'GET':
        # 处理服务器配置验证
        signature = request.args.get('signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        echostr = request.args.get('echostr', '')
        
        with open('logs/wechat_callback.log', 'a', encoding='utf-8') as f:
            f.write(f"验证参数: signature={signature}, timestamp={timestamp}, nonce={nonce}, echostr={echostr}\n")
        
        logging.debug(f"微信验证参数: signature={signature}, timestamp={timestamp}, nonce={nonce}, echostr={echostr}")
        
        # 配置token，需与公众号配置一致
        token = os.getenv("WECHAT_TOKEN", "voidcy")
        
        with open('logs/wechat_callback.log', 'a', encoding='utf-8') as f:
            f.write(f"使用Token: {token}\n")
        
        # 按照微信要求验证签名
        temp_list = [token, timestamp, nonce]
        temp_list.sort()
        temp_str = ''.join(temp_list)
        
        import hashlib
        hash_obj = hashlib.sha1()
        hash_obj.update(temp_str.encode('utf-8'))
        hashcode = hash_obj.hexdigest()
        
        # 验证签名
        with open('logs/wechat_callback.log', 'a', encoding='utf-8') as f:
            f.write(f"计算的签名: {hashcode}\n")
            f.write(f"微信的签名: {signature}\n")
            f.write(f"签名匹配: {hashcode == signature}\n")
        
        if hashcode == signature:
            logging.debug(f"微信服务器验证成功")
            return echostr
        
        logging.error(f"微信服务器验证失败: 计算的签名={hashcode}, 微信签名={signature}")
        return 'error'
    
    elif request.method == 'POST':
        # 处理微信服务器推送的消息和事件
        try:
            # 记录原始数据
            data = request.data
            logging.debug(f"收到微信推送数据: {data}")
            
            # 解析XML消息
            import xml.etree.ElementTree as ET
            xml_data = ET.fromstring(data)
            
            msg_type = xml_data.find('MsgType').text
            logging.debug(f"微信消息类型: {msg_type}")
            
            # 处理不同类型的消息
            if msg_type == 'event':
                # 处理事件消息
                event = xml_data.find('Event').text
                logging.debug(f"微信事件类型: {event}")
                
                if event == 'SCAN':
                    # 用户已关注公众号，扫描带参数二维码事件
                    event_key = xml_data.find('EventKey').text
                    from_user = xml_data.find('FromUserName').text
                    logging.debug(f"用户扫码事件: event_key={event_key}, openid={from_user}")
                    
                    # 提取和处理场景值
                    scene_str = extract_scene_str(event_key)
                    logging.debug(f"提取后的场景值: {scene_str}")
                    
                    # 更新二维码状态
                    success = WechatQrcode.update_scanned(scene_str, from_user)
                    logging.debug(f"更新扫码状态: {'成功' if success else '失败'}")
                    
                    # 返回被动回复消息
                    return """
                    <xml>
                        <ToUserName><![CDATA[%s]]></ToUserName>
                        <FromUserName><![CDATA[%s]]></FromUserName>
                        <CreateTime>%s</CreateTime>
                        <MsgType><![CDATA[text]]></MsgType>
                        <Content><![CDATA[您已成功扫码，请返回网页继续操作。]]></Content>
                    </xml>
                    """ % (from_user, xml_data.find('ToUserName').text, int(time.time()))
                
                elif event == 'subscribe':
                    # 用户订阅公众号事件
                    from_user = xml_data.find('FromUserName').text
                    logging.debug(f"用户关注事件: openid={from_user}")
                    
                    # 检查是否有场景值
                    event_key = xml_data.find('EventKey')
                    if event_key is not None and event_key.text:
                        # 提取场景值
                        scene_str = event_key.text
                        logging.debug(f"关注事件包含场景值: {scene_str}")
                        
                        # 提取和处理场景值
                        scene_str = extract_scene_str(scene_str)
                        logging.debug(f"提取后的场景值: {scene_str}")
                        
                        # 更新二维码状态
                        success = WechatQrcode.update_scanned(scene_str, from_user)
                        logging.debug(f"更新扫码状态: {'成功' if success else '失败'}")
                        
                        # 返回被动回复消息
                        return """
                        <xml>
                            <ToUserName><![CDATA[%s]]></ToUserName>
                            <FromUserName><![CDATA[%s]]></FromUserName>
                            <CreateTime>%s</CreateTime>
                            <MsgType><![CDATA[text]]></MsgType>
                            <Content><![CDATA[感谢关注！您已成功扫码，请返回网页继续操作。]]></Content>
                        </xml>
                        """ % (from_user, xml_data.find('ToUserName').text, int(time.time()))
                    
                    # 返回普通关注回复
                    return """
                    <xml>
                        <ToUserName><![CDATA[%s]]></ToUserName>
                        <FromUserName><![CDATA[%s]]></FromUserName>
                        <CreateTime>%s</CreateTime>
                        <MsgType><![CDATA[text]]></MsgType>
                        <Content><![CDATA[感谢关注剧本管理系统！]]></Content>
                    </xml>
                    """ % (from_user, xml_data.find('ToUserName').text, int(time.time()))
            
            # 默认回复
            return """
            <xml>
                <ToUserName><![CDATA[%s]]></ToUserName>
                <FromUserName><![CDATA[%s]]></FromUserName>
                <CreateTime>%s</CreateTime>
                <MsgType><![CDATA[text]]></MsgType>
                <Content><![CDATA[您的消息已收到。]]></Content>
            </xml>
            """ % (xml_data.find('FromUserName').text, xml_data.find('ToUserName').text, int(time.time()))
            
        except Exception as e:
            logging.error(f"处理微信消息错误: {e}", exc_info=True)
            return 'success'
    
    return 'success'

# 添加调试路由，仅在开发环境中使用
@auth.route('/debug_simulate_scan', methods=['POST'])
def debug_simulate_scan():
    """
    调试接口：模拟微信扫码
    仅在开发环境中使用
    """
    scene_str = request.form.get('scene_str')
    openid = request.form.get('openid')
    
    if not scene_str or not openid:
        return jsonify({
            'success': False,
            'message': '缺少必要参数'
        })
    
    # 更新二维码状态
    success = WechatQrcode.update_scanned(scene_str, openid)
    
    if success:
        # 检查用户是否存在，如果不存在，创建测试用户
        user = UserModel.query.filter_by(wx_openid=openid).first()
        if not user:
            try:
                # 创建新用户
                user = UserModel(f"wx_{openid}@test.com")
                user.wx_openid = openid
                user.wx_nickname = f"测试用户_{openid[:6]}"
                user.register_type = 'wechat'
                # 设置随机密码
                import random, string
                random_password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
                user.password_hash = hashlib.sha256(random_password.encode()).hexdigest()
                
                db.session.add(user)
                db.session.commit()
                logging.debug(f"创建测试用户成功: {user.email}")
            except Exception as e:
                db.session.rollback()
                logging.error(f"创建测试用户失败: {e}")
                return jsonify({
                    'success': False,
                    'message': f'创建用户失败: {e}'
                })
    
    return jsonify({
        'success': success,
        'message': '模拟扫码成功' if success else '模拟扫码失败'
    })

@auth.route('/wechat_test', methods=['GET', 'POST'])
def wechat_test():
    """
    测试路由，用于验证微信服务器是否能访问
    """
    try:
        # 写入文件日志
        with open('logs/wechat_test.log', 'a', encoding='utf-8') as f:
            f.write(f"\n----- 新测试请求 {datetime.now()} -----\n")
            f.write(f"请求方法: {request.method}\n")
            f.write(f"请求参数: {request.args}\n")
            if request.method == 'POST':
                f.write(f"请求数据: {request.data}\n")
            
        # 如果是GET请求，返回一个简单的HTML页面
        if request.method == 'GET':
            return """
            <html>
            <head><title>微信回调测试</title></head>
            <body>
                <h1>微信回调测试页面</h1>
                <p>此页面用于测试微信服务器是否能访问您的服务器。</p>
                <p>当前时间: {}</p>
            </body>
            </html>
            """.format(datetime.now())
        
        # 如果是POST请求，返回success
        return 'success'
    except Exception as e:
        # 记录错误
        with open('logs/wechat_test.log', 'a', encoding='utf-8') as f:
            f.write(f"发生错误: {str(e)}\n")
        return f"Error: {str(e)}" 