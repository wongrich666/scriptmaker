conda create -n scriptmaker python=3.12 -y
conda activate scriptmaker
cd c:\scriptMaker

pip install -r requirements.txt


# 将服务配置文件复制到 systemd 目录
sudo cp scriptmaker.service /etc/systemd/system/

# 创建日志目录
sudo mkdir -p /var/log/scriptmaker
sudo chown root:root /var/log/scriptmaker

# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启用服务（开机自启）
sudo systemctl enable scriptmaker

# 启动服务
sudo systemctl start scriptmaker

# 查看服务状态
sudo systemctl status scriptmaker

# 停止服务
sudo systemctl stop scriptmaker

# 重启服务
sudo systemctl restart scriptmaker

# 查看服务日志
sudo journalctl -u scriptmaker -f