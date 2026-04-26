# Wallpaper-Unpacker-GUI

一个轻量、离线、本地运行的 Wallpaper Engine 资源导出工具。  
支持从 `.pkg` / `.tex` 文件中提取图片资源，并提供 GUI + CLI 双模式。

## 特性

- 完全离线运行（无网络请求）
- 支持 `.pkg` / `.tex` 文件与目录批量解析
- 提供 GUI 图形界面 + CLI 命令行双模式
- 支持两种输出模式：
  - 默认结构化输出
  - `--same-folder` 扁平输出到同一目录
- 自动处理重名文件，避免覆盖
- 依赖少，开箱即用

## 快速开始

### (1) 安装依赖

```bash
pip install -r requirements.txt
```

### (2) 启动 GUI（默认方式）

```bash
python main.py
```

### (3) 命令行使用

```bash
python main.py <输入路径> <输出目录>
```

示例：

```bash
python main.py "D:/wallpaper_engine/projects" "D:/output"
```

## 常用命令

```bash
# 同目录扁平输出模式
python main.py "输入路径" "输出目录" --same-folder

# 禁用 GUI，仅 CLI 模式运行
python main.py --nogui

# 环境与依赖检查
python main.py --self-check

# 查看帮助
python main.py --help
```

## CLI 参数说明

| 参数 | 说明 |
| --- | --- |
| `input` | 输入文件或目录路径 |
| `output` | 输出目录 |
| `--same-folder` | 输出到同一目录（不分层级） |
| `--nogui` | 禁用 GUI 启动 |
| `--self-check` | 检查运行环境与依赖 |

## 数据目录

默认数据存储路径：

```text
~/.Wallpaper-Unpacker-GUI/
```

通过环境变量自定义：

Linux / macOS：

```bash
export WALLPAPER_UNPACKER_GUI_APP_DIR=/your/path
```

Windows PowerShell：

```powershell
$env:WALLPAPER_UNPACKER_GUI_APP_DIR="D:\Wallpaper-Unpacker-Data"
```

## Acknowledgements

This project is inspired by and refactored from [notscuffed/repkg](https://github.com/notscuffed/repkg), a Wallpaper Engine PKG/TEX extraction and conversion tool.

## License

MIT License