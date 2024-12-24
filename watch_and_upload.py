#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : watch_and_upload.py
@Time    : 2024/03/21
@Author  : Your Name
@Description : 文件监控和自动同步工具
    用于监控指定 Windows 目录下的文件变化，并自动将变更同步到 WSL 对应目录。
    支持多目录监控和文件排除规则配置。

Features:
    - 支持多目录同步配置
    - 支持文件排除规则（使用 glob 模式匹配）
    - 实时监控文件创建和修改事件
    - 保持目录结构同步
"""

import os
import shutil
import time
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import threading
from PIL import Image, ImageDraw, ImageTk
import pystray
from pystray import MenuItem as item
import winreg
import sys
import ctypes

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "sync_config.json")

# 添加自启动相关的常量
STARTUP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "FileSync"

def create_default_icon():
    """创建默认图标并保存为 ICO 文件"""
    try:
        # 创建一个 32x32 的图像
        size = (32, 32)
        image = Image.new('RGBA', size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        
        # 绘制一个简单的同步图标
        # 外圆
        draw.ellipse([2, 2, 29, 29], outline=(0, 120, 215), width=2)
        # 箭头 1
        draw.arc([8, 8, 23, 23], 0, 270, fill=(0, 120, 215), width=2)
        # 箭头 2
        draw.polygon([(23, 15), (23, 8), (30, 12)], fill=(0, 120, 215))
        
        # 保存为 ICO 文件，使用绝对路径
        icon_path = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'sync_icon.ico')
        image.save(icon_path, format='ICO')
        return True
    except Exception as e:
        logging.warning(f"创建默认图标时出错：{e}")
        return False

class SyncApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("文件同步工具")
        self.geometry("800x600")
        
        # 添加托盘相关属性
        self.tray_icon = None
        self.is_minimized = False
        
        # 设置图标
        try:
            # 使用绝对路径加载图标
            icon_path = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'sync_icon.ico')
            self.iconbitmap(icon_path)
        except tk.TclError:
            # 如果图标不存在，尝试创建默认图标
            if create_default_icon():
                try:
                    self.iconbitmap(icon_path)
                except tk.TclError:
                    logging.warning("无法设置应用程序图标")
        
        # 加载配置
        self.config = self.load_config()
        
        self.create_widgets()
        self.observers = []
        self.is_watching = False
        
        # 设置窗口关闭事件处理
        self.protocol('WM_DELETE_WINDOW', self.minimize_to_tray)
        
        # 添加自启动状态
        self.autostart = self.get_autostart_status()
        
        # 创建系统托盘
        self.setup_tray()
        
        # 处理命令行参数
        if len(sys.argv) > 1 and sys.argv[1] == '--minimized':
            self.after(0, self.minimize_to_tray)
        
        # 启动后自动开始监控
        self.after(1000, self.start_monitoring)  # 延迟1秒后开始监控
        
    def create_widgets(self):
        # 创建主框架
        main_frame = ttk.Frame(self)
        main_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        
        # 创建上下分隔的面板，使用权重控制比例
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 同步配置列表框架
        list_frame = ttk.LabelFrame(top_frame, text="同步配置")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 同步配置列表
        self.sync_list = ttk.Treeview(list_frame, columns=("本地路径", "WSL路径", "排除规则"), show="headings", height=5)  # 设置初始显示5行
        self.sync_list.heading("本地路径", text="本地路径")
        self.sync_list.heading("WSL路径", text="WSL路径")
        self.sync_list.heading("排除规则", text="排除规则")
        self.sync_list.pack(fill=tk.BOTH, expand=True)
        
        # 为配置列表添加滚动条
        list_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.sync_list.yview)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.sync_list.configure(yscrollcommand=list_scrollbar.set)
        
        # 创建日志显示区域
        log_frame = ttk.LabelFrame(main_frame, text="监控日志")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # 按钮框架
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="添加配置", command=self.add_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="编辑配置", command=self.edit_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="删除配置", command=self.delete_config).pack(side=tk.LEFT, padx=5)
        
        self.watch_btn = ttk.Button(btn_frame, text="开始监控", command=self.toggle_watching)
        self.watch_btn.pack(side=tk.LEFT, padx=5)
        
        # 更新配置列表显示
        self.update_config_list()
    
    def load_config(self):
        """加载配置文件"""
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logging.info(f"成功加载配置文件: {CONFIG_FILE}")
                return config
        except FileNotFoundError:
            logging.warning(f"配置文件不存在，将创建新配置: {CONFIG_FILE}")
            default_config = {"watch_dirs": []}
            self.save_config(default_config)
            return default_config
        except json.JSONDecodeError as e:
            logging.error(f"配置文件格式错误: {e}")
            return {"watch_dirs": []}
        except Exception as e:
            logging.error(f"加载配置文件时出错: {e}")
            return {"watch_dirs": []}
    
    def save_config(self, config=None):
        """保存配置文件"""
        if config is None:
            config = self.config
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            logging.info(f"配置已保存到: {CONFIG_FILE}")
        except Exception as e:
            logging.error(f"保存配置文件时出错: {e}")
            messagebox.showerror("错误", f"保存配置失败: {e}")
    
    def update_config_list(self):
        # 清空现有项
        for item in self.sync_list.get_children():
            self.sync_list.delete(item)
        
        # 添加配置项
        for dir_config in self.config.get("watch_dirs", []):
            self.sync_list.insert("", tk.END, values=(
                dir_config["local"],
                dir_config["wsl"],
                ", ".join(dir_config.get("exclude_patterns", []))
            ))

    def add_config(self):
        dialog = ConfigDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.config.setdefault("watch_dirs", []).append(dialog.result)
            self.save_config()
            self.update_config_list()

    def delete_config(self):
        selected = self.sync_list.selection()
        if not selected:
            return
        
        index = self.sync_list.index(selected[0])
        self.config["watch_dirs"].pop(index)
        self.save_config()
        self.update_config_list()

    def edit_config(self):
        """编辑选中的配置"""
        selected = self.sync_list.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择要编辑的配置")
            return
        
        index = self.sync_list.index(selected[0])
        current_config = self.config["watch_dirs"][index]
        
        dialog = ConfigDialog(self, edit_mode=True, initial_config=current_config)
        self.wait_window(dialog)
        
        if dialog.result:
            self.config["watch_dirs"][index] = dialog.result
            self.save_config()
            self.update_config_list()

    def toggle_watching(self):
        if not self.is_watching:
            self.start_watching()
            self.watch_btn.configure(text="停止监控")
            if self.tray_icon:
                self.tray_icon.title = "文件同步工具 (监控中)"
        else:
            self.stop_watching()
            self.watch_btn.configure(text="开始监控")
            if self.tray_icon:
                self.tray_icon.title = "文件同步工具"
        
        self.is_watching = not self.is_watching

    def start_watching(self):
        # 清空日志显示
        self.log_text.delete(1.0, tk.END)
        self.log_text.insert(tk.END, "开始监控...\n")
        
        # 配置日志处理器
        self.setup_logging()
        
        for watch_config in self.config.get("watch_dirs", []):
            event_handler = FileUploadHandler(watch_config)
            observer = Observer()
            observer.schedule(event_handler, watch_config['local'], recursive=True)
            observer.start()
            self.observers.append(observer)
            logging.info(f"正在监听 {watch_config['local']} 下的文件变化...")

    def stop_watching(self):
        for observer in self.observers:
            observer.stop()
            observer.join()
        self.observers.clear()

    def setup_logging(self):
        # 创建自定义的日志处理器
        class TextHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget

            def emit(self, record):
                msg = self.format(record)
                def append():
                    self.text_widget.insert(tk.END, msg + '\n')
                    self.text_widget.see(tk.END)
                self.text_widget.after(0, append)

        # 清除现有的处理器
        logger = logging.getLogger()
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # 添加控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(console_handler)

        # 添加文本窗口处理器
        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(text_handler)

    def setup_tray(self):
        """设置系统托盘"""
        # 使用绝对路径获取图标
        icon_path = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'sync_icon.ico')
        if not os.path.exists(icon_path):
            create_default_icon()
        
        # 创建托盘菜单
        menu = (
            item('显示', self.show_window),
            item('开始监控', self.start_monitoring),
            item('停止监控', self.stop_monitoring),
            item('开机自启', self.toggle_autostart, checked=lambda _: self.autostart),
            item('退出', self.quit_app)
        )
        
        try:
            # 加载图标
            image = Image.open(icon_path)
            self.tray_icon = pystray.Icon("sync_tool", image, "文件同步工具", menu)
            
            # 在新线程中运行托盘图标
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            logging.error(f"设置托盘图标失败: {e}")
            # 如果设置托盘图标失败，仍然允许程序继续运行
            self.tray_icon = None
    
    def minimize_to_tray(self):
        """最小化到系统托盘"""
        self.withdraw()
        self.is_minimized = True
    
    def show_window(self):
        """显示窗口"""
        self.deiconify()
        self.is_minimized = False
    
    def start_monitoring(self):
        """从托盘开始监控"""
        if not self.is_watching:
            self.toggle_watching()
    
    def stop_monitoring(self):
        """从托盘停止监控"""
        if self.is_watching:
            self.toggle_watching()
    
    def quit_app(self):
        """完全退出应用程序"""
        self.stop_watching()
        if self.tray_icon:
            self.tray_icon.stop()
        self.quit()

    def get_autostart_status(self):
        """获取当前自启动状态"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                STARTUP_REG_PATH,
                0,
                winreg.KEY_READ
            )
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return sys.executable in value
        except WindowsError:
            return False

    def set_autostart(self, enable=True):
        """设置开机自启动"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                STARTUP_REG_PATH,
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_READ
            )
            
            if enable:
                # 获取当前执行文件的路径
                exe_path = sys.executable
                # 添加启动参数，使程序启动时最小化到托盘
                value = f'"{exe_path}" --minimized'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, value)
                self.log_text.insert(tk.END, "已启用开机自启动\n")
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    self.log_text.insert(tk.END, "已禁用开机自启动\n")
                except WindowsError:
                    pass
            
            winreg.CloseKey(key)
            self.autostart = enable
            # 更新托盘图标菜单状态
            self.tray_icon.update_menu()
            return True
        except Exception as e:
            logging.error(f"设置开机自启动失败: {e}")
            messagebox.showerror("错误", f"设置开机自启动失败: {e}")
            return False

    def toggle_autostart(self):
        """切换开机自启动状态"""
        self.set_autostart(not self.autostart)

class ConfigDialog(tk.Toplevel):
    def __init__(self, parent, edit_mode=False, initial_config=None):
        super().__init__(parent)
        self.title("编辑同步配置" if edit_mode else "添加同步配置")
        self.geometry("400x300")
        self.result = None
        self.edit_mode = edit_mode
        self.initial_config = initial_config
        
        self.create_widgets()
        
        # 如果是编辑模式，填充现有配置
        if edit_mode and initial_config:
            self.local_path.insert(0, initial_config["local"])
            self.wsl_path.insert(0, initial_config["wsl"])
            self.exclude_patterns.insert("1.0", "\n".join(initial_config.get("exclude_patterns", [])))
    
    def create_widgets(self):
        # 创建主框架
        main_frame = ttk.Frame(self)
        main_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        
        # 本地路径
        path_frame = ttk.Frame(main_frame)
        path_frame.pack(fill=tk.X, pady=5)
        ttk.Label(path_frame, text="本地路径:").pack(side=tk.LEFT)
        self.local_path = ttk.Entry(path_frame)
        self.local_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(path_frame, text="浏览", command=lambda: self.browse_path(self.local_path)).pack(side=tk.RIGHT)
        
        # WSL路径
        wsl_frame = ttk.Frame(main_frame)
        wsl_frame.pack(fill=tk.X, pady=5)
        ttk.Label(wsl_frame, text="WSL路径:").pack(side=tk.LEFT)
        self.wsl_path = ttk.Entry(wsl_frame)
        self.wsl_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(wsl_frame, text="浏览", command=lambda: self.browse_path(self.wsl_path)).pack(side=tk.RIGHT)
        
        # 排除规则
        ttk.Label(main_frame, text="排除规则 (每行一个):").pack(pady=5)
        self.exclude_patterns = tk.Text(main_frame, height=5)
        self.exclude_patterns.pack(fill=tk.BOTH, expand=True, padx=5)
        
        # 按钮框架
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        
        # 确定和取消按钮
        ttk.Button(btn_frame, text="保存" if self.edit_mode else "确定", 
                  command=self.save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.RIGHT, padx=5)
    
    def browse_path(self, entry):
        path = filedialog.askdirectory()
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)
    
    def save(self):
        patterns = [p.strip() for p in self.exclude_patterns.get("1.0", tk.END).split('\n') if p.strip()]
        self.result = {
            "local": self.local_path.get(),
            "wsl": self.wsl_path.get(),
            "exclude_patterns": patterns
        }
        self.destroy()

class FileUploadHandler(FileSystemEventHandler):
    def __init__(self, watch_config):
        self.watch_config = watch_config
        super().__init__()

    def should_process_file(self, file_path):
        """检查文件是否应该被处理"""
        from fnmatch import fnmatch

        file_name = os.path.basename(file_path)
        relative_path = os.path.relpath(file_path, self.watch_config['local'])
        path_parts = relative_path.split(os.sep)  # 将路径分割成各个部分

        # 添加对临时文件的检查
        if file_name.endswith('~') or file_name.startswith('.'):
            logging.info(f"跳过临时文件: {file_path}")
            return False

        for pattern in self.watch_config.get('exclude_patterns', []):
            # 检查路径中的每个部分是否匹配排除规则
            if any(fnmatch(part, pattern.rstrip('/*')) for part in path_parts):
                logging.info(f"跳过排除的文件: {file_path}")
                return False
            # 保对完整路径的匹配检查
            if fnmatch(relative_path, pattern):
                logging.info(f"跳过排除的文件: {file_path}")
                return False
        return True

    def on_modified(self, event):
        # 只有文件被修改时触发
        if event.is_directory:
            return
        if self.should_process_file(event.src_path):
            self.copy_to_wsl(event.src_path)

    def on_created(self, event):
        # 只有文件被创建时触发
        if event.is_directory:
            return
        if self.should_process_file(event.src_path):
            self.copy_to_wsl(event.src_path)

    def copy_to_wsl(self, file_path):
        """将文件复制到 WSL"""
        logging.info(f"文件已变化，准备复制到 WSL: {file_path}")

        if os.path.exists(file_path):
            try:
                # 获取相对路径，以保持目录结构
                rel_path = os.path.relpath(file_path, self.watch_config['local'])
                destination_path = os.path.join(self.watch_config['wsl'], rel_path)

                # 确保目标目录存在
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)

                # 复制文件到 WSL
                shutil.copy2(file_path, destination_path)
                logging.info(f"文件成功复制到 WSL: {destination_path}")
            except Exception as e:
                logging.error(f"复制文件到 WSL 时出错: {e}")


if __name__ == "__main__":
    # 设置应用程序ID，确保托盘图标正常显示
    myappid = f'mycompany.{APP_NAME}.1.0'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    
    app = SyncApp()
    app.mainloop()
