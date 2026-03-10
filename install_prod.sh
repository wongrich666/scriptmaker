#!/bin/bash

# 生产环境安装脚本
# 使用方法: sudo ./install_prod.sh

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用sudo运行此脚本"
    exit 1
fi

# 更新系统包
echo "更新系统包..."
apt update && apt upgrade -y

# 安装必要的系统依赖
echo "安装系统依赖..."
apt install -y python3 python3-pip python3-venv nginx

# 检查nginx是否正确安装
if ! command -v nginx &> /dev/null; then
    echo "错误: nginx安装失败"
    exit 1
fi

# 创建nginx配置目录（如果不存在）
echo "创建nginx配置目录..."
mkdir -p /etc/nginx/sites-available
mkdir -p /etc/nginx/sites-enabled

# 创建应用目录
echo "创建应用目录..."
mkdir -p /opt/scriptMaker
mkdir -p /var/log/scriptmaker

# 复制应用文件到生产目录
echo "复制应用文件..."
cp -r . /opt/scriptMaker/
chown -R root:root /opt/scriptMaker
chmod -R 755 /opt/scriptMaker

# 创建虚拟环境
echo "创建虚拟环境..."
cd /opt/scriptMaker
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 安装systemd服务
echo "安装systemd服务..."
cp scriptmaker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable scriptmaker.service

# 创建nginx配置
echo "配置nginx..."
cat > /etc/nginx/sites-available/scriptmaker << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:60002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# 启用nginx站点
ln -sf /etc/nginx/sites-available/scriptmaker /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# 测试nginx配置
nginx -t

# 启动应用服务
echo "启动应用服务..."
systemctl start scriptmaker.service
sleep 3

# 检查应用服务状态
if systemctl is-active --quiet scriptmaker.service; then
    echo "应用服务启动成功"
else
    echo "应用服务启动失败，查看日志："
    journalctl -u scriptmaker.service -n 20
fi

# 重启nginx
echo "重启nginx..."
systemctl restart nginx

echo "安装完成！"
echo "应用将在 http://your-server-ip 上运行"
echo "使用以下命令管理服务："
echo "  sudo systemctl status scriptmaker.service"
echo "  sudo systemctl restart scriptmaker.service"
echo "  sudo systemctl stop scriptmaker.service"
echo ""
echo "如果遇到问题，请检查："
echo "1. 应用服务状态: sudo systemctl status scriptmaker.service"
echo "2. 应用日志: sudo journalctl -u scriptmaker.service -f"
echo "3. nginx状态: sudo systemctl status nginx"
echo "4. nginx日志: sudo tail -f /var/log/nginx/error.log"
