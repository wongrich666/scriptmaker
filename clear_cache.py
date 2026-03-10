#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存清理脚本 - 解决Flask模板缓存问题
"""
import os
import shutil
import time
import subprocess
import sys

def clear_python_cache():
    """清理Python缓存文件"""
    print("正在清理Python缓存...")
    
    # 清理__pycache__目录
    for root, dirs, files in os.walk('.'):
        for dir_name in dirs:
            if dir_name == '__pycache__':
                cache_path = os.path.join(root, dir_name)
                try:
                    shutil.rmtree(cache_path)
                    print(f"已删除: {cache_path}")
                except Exception as e:
                    print(f"删除失败 {cache_path}: {e}")
    
    # 清理.pyc文件
    for root, dirs, files in os.walk('.'):
        for file_name in files:
            if file_name.endswith('.pyc'):
                pyc_path = os.path.join(root, file_name)
                try:
                    os.remove(pyc_path)
                    print(f"已删除: {pyc_path}")
                except Exception as e:
                    print(f"删除失败 {pyc_path}: {e}")

def clear_flask_cache():
    """清理Flask相关缓存"""
    print("正在清理Flask缓存...")
    
    # 清理可能的Flask实例缓存
    cache_dirs = [
        'instance',
        '.flask_session',
        'flask_session',
        'cache',
        '.cache'
    ]
    
    for cache_dir in cache_dirs:
        if os.path.exists(cache_dir):
            try:
                shutil.rmtree(cache_dir)
                print(f"已删除: {cache_dir}")
            except Exception as e:
                print(f"删除失败 {cache_dir}: {e}")

def clear_browser_cache_instructions():
    """显示浏览器缓存清理说明"""
    print("\n" + "="*60)
    print("浏览器缓存清理说明:")
    print("="*60)
    print("1. 按 F12 打开开发者工具")
    print("2. 右键点击刷新按钮")
    print("3. 选择 '清空缓存并硬性重新加载'")
    print("4. 或者按 Ctrl+Shift+R 强制刷新")
    print("5. 在开发者工具 -> Network 标签页中勾选 'Disable cache'")
    print("="*60)

def restart_app():
    """重启应用"""
    print("\n正在重启应用...")
    
    # 查找并停止Python进程
    try:
        # Windows
        if os.name == 'nt':
            result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe'], 
                                 capture_output=True, text=True, shell=True)
            if 'python.exe' in result.stdout:
                print("发现Python进程，正在停止...")
                subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], 
                             capture_output=True, shell=True)
                time.sleep(2)
        else:
            # Linux/Mac
            result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
            if 'python' in result.stdout:
                print("发现Python进程，正在停止...")
                subprocess.run(['pkill', '-f', 'python.*app.py'], 
                             capture_output=True)
                time.sleep(2)
    except Exception as e:
        print(f"停止进程失败: {e}")
    
    print("应用已停止，请手动重新启动:")
    print("Windows: .\\start_dev.bat")
    print("Linux: ./start_prod.sh")

def main():
    print("Flask缓存清理工具")
    print("="*40)
    
    # 清理Python缓存
    clear_python_cache()
    
    # 清理Flask缓存
    clear_flask_cache()
    
    # 显示浏览器缓存清理说明
    clear_browser_cache_instructions()
    
    # 重启应用
    restart_app()
    
    print("\n缓存清理完成！")
    print("如果问题仍然存在，请检查:")
    print("1. 是否有反向代理缓存（如Nginx）")
    print("2. 是否有CDN缓存")
    print("3. 浏览器是否完全清理了缓存")

if __name__ == '__main__':
    main()
