#!/bin/bash

# 部署脚本 - 用于更新应用
# 使用方法: sudo ./deploy.sh

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用sudo运行此脚本"
    exit 1
fi

echo "开始部署更新..."

# 停止服务
echo "停止服务..."
systemctl stop scriptmaker.service

# 备份当前版本
echo "备份当前版本..."
cd /opt
if [ -d "scriptMaker" ]; then
    mv scriptMaker scriptMaker.backup.$(date +%Y%m%d_%H%M%S)
fi

# 复制新版本
echo "复制新版本..."
cp -r . /opt/scriptMaker/
chown -R www-data:www-data /opt/scriptMaker
chmod -R 755 /opt/scriptMaker

# 更新虚拟环境
echo "更新虚拟环境..."
cd /opt/scriptMaker
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 重启服务
echo "重启服务..."
systemctl start scriptmaker.service

echo "部署完成！"
echo "使用以下命令检查服务状态："
echo "  sudo systemctl status scriptmaker.service"
