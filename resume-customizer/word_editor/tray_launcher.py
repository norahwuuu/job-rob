"""
Windows 系统托盘启动器 - 简历优化 API 服务

功能：
- 系统托盘图标
- 启动/停止 API 服务器
- 打开日志目录
- 开机自启设置
"""

import os
import sys
import subprocess
import threading
import webbrowser
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw
except ImportError:
    print("请先安装依赖: pip install pystray Pillow")
    print("运行: pip install -r requirements.txt")
    sys.exit(1)

from config import API_HOST, API_PORT, DEFAULT_OUTPUT_DIR, LOG_FILE_PATH


class TrayApp:
    """系统托盘应用"""
    
    def __init__(self):
        self.server_process = None
        self.icon = None
        self.is_running = False
        
    def create_icon_image(self, running=False):
        """创建托盘图标"""
        # 创建 64x64 图像
        size = 64
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # 绘制圆形背景
        if running:
            # 运行中 - 绿色
            draw.ellipse([4, 4, size-4, size-4], fill='#34a853', outline='#2d9249', width=2)
        else:
            # 已停止 - 灰色
            draw.ellipse([4, 4, size-4, size-4], fill='#9aa0a6', outline='#5f6368', width=2)
        
        # 绘制文字 "CV"
        try:
            from PIL import ImageFont
            # 尝试使用系统字体
            font = ImageFont.truetype("arial.ttf", 24)
        except:
            font = ImageFont.load_default()
        
        # 居中绘制文字
        text = "CV"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (size - text_width) // 2
        y = (size - text_height) // 2 - 2
        draw.text((x, y), text, fill='white', font=font)
        
        return image
    
    def update_icon(self):
        """更新托盘图标状态"""
        if self.icon:
            self.icon.icon = self.create_icon_image(self.is_running)
            status = "运行中" if self.is_running else "已停止"
            self.icon.title = f"简历优化服务 - {status}"
    
    def start_server(self, icon=None, item=None):
        """启动 API 服务器"""
        if self.is_running:
            print("服务器已在运行中")
            return
        
        try:
            # 获取当前脚本所在目录
            script_dir = Path(__file__).parent
            
            # 启动服务器进程
            self.server_process = subprocess.Popen(
                [sys.executable, "-m", "resume_modifier.api_server"],
                cwd=str(script_dir),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            self.is_running = True
            self.update_icon()
            print(f"API 服务已启动: http://{API_HOST}:{API_PORT}")
            
        except Exception as e:
            print(f"启动服务器失败: {e}")
    
    def stop_server(self, icon=None, item=None):
        """停止 API 服务器"""
        if self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            finally:
                self.server_process = None
        
        self.is_running = False
        self.update_icon()
        print("API 服务已停止")
    
    def toggle_server(self, icon=None, item=None):
        """切换服务器状态"""
        if self.is_running:
            self.stop_server()
        else:
            self.start_server()
    
    def open_api_docs(self, icon=None, item=None):
        """打开 API 文档"""
        if self.is_running:
            webbrowser.open(f"http://{API_HOST}:{API_PORT}/docs")
        else:
            print("服务器未运行")
    
    def open_output_dir(self, icon=None, item=None):
        """打开输出目录"""
        output_dir = Path(DEFAULT_OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if sys.platform == 'win32':
            os.startfile(str(output_dir))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(output_dir)])
        else:
            subprocess.run(['xdg-open', str(output_dir)])
    
    def open_log_file(self, icon=None, item=None):
        """打开日志文件"""
        log_file = Path(LOG_FILE_PATH)
        if log_file.exists():
            if sys.platform == 'win32':
                os.startfile(str(log_file))
            elif sys.platform == 'darwin':
                subprocess.run(['open', str(log_file)])
            else:
                subprocess.run(['xdg-open', str(log_file)])
        else:
            print("日志文件不存在")
    
    def add_to_startup(self, icon=None, item=None):
        """添加到 Windows 启动项"""
        if sys.platform != 'win32':
            print("此功能仅支持 Windows")
            return
        
        try:
            import winreg
            
            # 获取当前脚本路径
            script_path = Path(__file__).resolve()
            python_path = sys.executable
            
            # 命令行
            command = f'"{python_path}" "{script_path}"'
            
            # 打开注册表
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE
            )
            
            # 设置启动项
            winreg.SetValueEx(key, "ResumeOptimizerService", 0, winreg.REG_SZ, command)
            winreg.CloseKey(key)
            
            print("已添加到开机启动")
            
        except Exception as e:
            print(f"添加启动项失败: {e}")
    
    def remove_from_startup(self, icon=None, item=None):
        """从 Windows 启动项移除"""
        if sys.platform != 'win32':
            print("此功能仅支持 Windows")
            return
        
        try:
            import winreg
            
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE
            )
            
            try:
                winreg.DeleteValue(key, "ResumeOptimizerService")
                print("已从开机启动移除")
            except FileNotFoundError:
                print("启动项不存在")
            
            winreg.CloseKey(key)
            
        except Exception as e:
            print(f"移除启动项失败: {e}")
    
    def quit_app(self, icon=None, item=None):
        """退出应用"""
        self.stop_server()
        if self.icon:
            self.icon.stop()
    
    def create_menu(self):
        """创建托盘菜单"""
        return pystray.Menu(
            item(
                '启动/停止服务',
                self.toggle_server,
                default=True
            ),
            item.SEPARATOR,
            item('打开 API 文档', self.open_api_docs),
            item('打开输出目录', self.open_output_dir),
            item('打开日志文件', self.open_log_file),
            item.SEPARATOR,
            item(
                '开机启动',
                pystray.Menu(
                    item('添加到启动项', self.add_to_startup),
                    item('从启动项移除', self.remove_from_startup),
                )
            ),
            item.SEPARATOR,
            item('退出', self.quit_app),
        )
    
    def run(self, auto_start=True):
        """运行托盘应用"""
        print("=" * 50)
        print("简历优化服务 - 系统托盘模式")
        print("=" * 50)
        print(f"API 地址: http://{API_HOST}:{API_PORT}")
        print(f"输出目录: {DEFAULT_OUTPUT_DIR}")
        print(f"日志文件: {LOG_FILE_PATH}")
        print("=" * 50)
        
        # 创建图标
        self.icon = pystray.Icon(
            "resume_optimizer",
            self.create_icon_image(False),
            "简历优化服务 - 已停止",
            self.create_menu()
        )
        
        # 自动启动服务器
        if auto_start:
            threading.Timer(1.0, self.start_server).start()
        
        # 运行托盘
        self.icon.run()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='简历优化服务 - 系统托盘启动器')
    parser.add_argument('--no-auto-start', action='store_true', help='不自动启动服务器')
    args = parser.parse_args()
    
    app = TrayApp()
    app.run(auto_start=not args.no_auto_start)


if __name__ == "__main__":
    main()
