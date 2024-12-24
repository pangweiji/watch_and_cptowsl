import PyInstaller.__main__
import os
import shutil

# 软件名称
APP_NAME = "FileSync"

# 清理旧的构建文件
if os.path.exists('dist'):
    shutil.rmtree('dist')
if os.path.exists('build'):
    shutil.rmtree('build')

# PyInstaller 打包配置
PyInstaller.__main__.run([
    'watch_and_upload.py',
    f'--name={APP_NAME}',
    '--onefile',
    '--windowed',
    '--icon=sync_icon.ico',
    '--add-data=sync_icon.ico;.',
    '--hidden-import=PIL._tkinter_finder',
])

# 创建最终的程序目录
final_dir = os.path.join('dist', APP_NAME)
if os.path.exists(final_dir):
    shutil.rmtree(final_dir)
os.makedirs(final_dir)

# 移动可执行文件到程序目录
shutil.move(os.path.join('dist', f'{APP_NAME}.exe'), os.path.join(final_dir, f'{APP_NAME}.exe'))

# 复制其他必要文件到程序目录
if os.path.exists('sync_icon.ico'):
    shutil.copy2('sync_icon.ico', os.path.join(final_dir, 'sync_icon.ico'))
if os.path.exists('sync_config.json'):
    shutil.copy2('sync_config.json', os.path.join(final_dir, 'sync_config.json'))

print(f"\n构建完成！程序文件已保存到: {os.path.abspath(final_dir)}") 