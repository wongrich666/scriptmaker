#!/bin/bash

# 故障排除脚本
# 使用方法: sudo ./troubleshoot.sh

echo "=== ScriptMaker 生产环境故障排除 ==="
echo ""

# 检查系统服务状态
echo "1. 检查系统服务状态..."
echo "应用服务状态:"
systemctl status scriptmaker.service --no-pager -l
echo ""

echo "nginx服务状态:"
systemctl status nginx --no-pager -l
echo ""

# 检查端口占用
echo "2. 检查端口占用..."
echo "端口60002占用情况:"
netstat -tlnp | grep :60002 || echo "端口60002未被占用"
echo ""

echo "端口80占用情况:"
netstat -tlnp | grep :80 || echo "端口80未被占用"
echo ""

# 检查应用日志
echo "3. 检查应用日志..."
echo "最近的应用日志:"
journalctl -u scriptmaker.service -n 20 --no-pager
echo ""

# 检查nginx日志
echo "4. 检查nginx日志..."
if [ -f "/var/log/nginx/error.log" ]; then
    echo "nginx错误日志:"
    tail -n 10 /var/log/nginx/error.log
else
    echo "nginx错误日志文件不存在"
fi
echo ""

# 检查文件权限
echo "5. 检查文件权限..."
echo "应用目录权限:"
ls -la /opt/scriptMaker/
echo ""

# 检查虚拟环境
echo "6. 检查虚拟环境..."
if [ -d "/opt/scriptMaker/venv" ]; then
    echo "虚拟环境存在"
    echo "Python版本:"
    /opt/scriptMaker/venv/bin/python --version
    echo "已安装的包:"
    /opt/scriptMaker/venv/bin/pip list
else
    echo "虚拟环境不存在"
fi
echo ""

# 检查配置文件
echo "7. 检查配置文件..."
echo "nginx配置:"
nginx -t
echo ""

echo "systemd服务配置:"
cat /etc/systemd/system/scriptmaker.service
echo ""

echo "=== 故障排除完成 ==="
echo ""
echo "如果应用服务未运行，请尝试："
echo "sudo systemctl restart scriptmaker.service"
echo ""
echo "如果nginx未运行，请尝试："
echo "sudo systemctl restart nginx"
echo ""
echo "查看实时日志："
echo "sudo journalctl -u scriptmaker.service -f"
