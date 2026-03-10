#!/bin/bash

# 生产环境启动脚本
# 使用方法: ./start_prod.sh

# 设置环境变量
export FLASK_ENV=production
export FLASK_APP=app.py
export FLASK_DEBUG=false

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到Python3，请先安装Python3"
    exit 1
fi

# 检查pip是否安装
if ! command -v pip3 &> /dev/null; then
    echo "错误: 未找到pip3，请先安装pip3"
    exit 1
fi

# 创建虚拟环境（如果不存在）
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 升级pip
echo "升级pip..."
pip install --upgrade pip

# 安装依赖
echo "正在安装依赖..."
pip install -r requirements.txt

# 检查是否安装成功
if [ $? -ne 0 ]; then
    echo "错误: 依赖安装失败"
    exit 1
fi

# 检查端口是否被占用
PORT=60002
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null ; then
    echo "端口 $PORT 已被占用，正在停止占用进程..."
    lsof -ti:$PORT | xargs kill -9
    sleep 2
fi

# 启动应用
echo "正在启动应用..."
echo "环境变量: FLASK_ENV=$FLASK_ENV, FLASK_DEBUG=$FLASK_DEBUG"
python app.py
