#!/bin/bash

# 测试应用启动脚本
# 使用方法: ./test_app.sh

echo "=== 测试应用启动 ==="

# 检查当前目录
echo "当前目录: $(pwd)"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "安装依赖..."
pip install -r requirements.txt

# 设置环境变量
export FLASK_ENV=production
export FLASK_APP=app.py
export FLASK_DEBUG=false

# 测试应用启动
echo "测试应用启动..."
echo "环境变量: FLASK_ENV=$FLASK_ENV, FLASK_DEBUG=$FLASK_DEBUG"

# 检查端口占用
PORT=60002
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null ; then
    echo "端口 $PORT 已被占用，正在停止占用进程..."
    lsof -ti:$PORT | xargs kill -9
    sleep 2
fi

# 尝试启动应用（后台运行）
echo "启动应用（测试模式）..."
timeout 10s python app.py &
APP_PID=$!

# 等待应用启动
sleep 3

# 检查应用是否启动
if ps -p $APP_PID > /dev/null; then
    echo "应用启动成功，PID: $APP_PID"
    echo "测试访问应用..."
    
    # 测试应用响应
    if curl -s http://localhost:60002/ > /dev/null; then
        echo "应用响应正常"
    else
        echo "应用响应异常"
    fi
    
    # 停止测试应用
    echo "停止测试应用..."
    kill $APP_PID
else
    echo "应用启动失败"
fi

echo "=== 测试完成 ==="
