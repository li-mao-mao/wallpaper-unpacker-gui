<p align="right">
  <a href="./README.md">English</a> | 
  <a href="./README_zh.md">简体中文</a>
</p>

# Wallpaper-Unpacker-GUI

A lightweight, offline, locally running Wallpaper Engine resource export tool.

Supports extracting image resources from `.pkg` / `.tex` files and provides both GUI and CLI modes.

## Features

- Runs completely offline (no network requests)

- Supports batch parsing of `.pkg` / `.tex` files and directories

- Provides dual-mode GUI + CLI command line

- Supports two output modes:

- Default structured output

- `--same-folder` flattened output to the same directory

- Automatically handles duplicate filenames to avoid overwriting

- Few dependencies, ready to use out of the box

## Quick Start

### (1) Install Dependencies

```bash
pip install -r requirements.txt

```

### (2) Start the GUI (default mode)

```bash
python main.py

```

### (3) Command Line Usage

```bash
python main.py <input path> <output directory>

```

Example:

```bash
python main.py "D:/wallpaper_engine/projects" "D:/output"

```

## Common Commands

```bash

# Same-directory flat output mode

python main.py "input path" "output directory" --same-folder

# Disable GUI, run only in CLI mode

python main.py --nogui

# Environment and dependency checks

python main.py --self-check

# View help

python main.py --help

```

## CLI Parameter Description

| Parameter | Description |

| --- | --- |

| `input` | Input file or directory path |

| `output` | Output directory |

| `--same-folder` | Output to the same directory (no hierarchical structure) |

| `--nogui` | Disable GUI startup |

| `--self-check` | Check runtime environment and dependencies |

## Data Directory

Default data storage path:

```text
~/.Wallpaper-Unpacker-GUI/

```
Customizable via environment variables:

Linux / macOS:

```bash
export WALLPAPER_UNPACKER_GUI_APP_DIR=/your/path
```

Windows PowerShell:

```powershell
$env:WALLPAPER_UNPACKER_GUI_APP_DIR="D:\Wallpaper-Unpacker-Data"
```

## Acknowledgements

This project is inspired by and refactored from [notscuffed/repkg](https://github.com/notscuffed/repkg), a Wallpaper Engine PKG/TEX extraction and conversion tool.

## License

MIT License