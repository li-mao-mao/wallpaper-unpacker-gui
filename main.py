import argparse
import sys
from pathlib import Path

from app.extractor import CancelledError, Stats, count_exportable_items, process_input

APP_NAME = "Wallpaper-Unpacker-GUI"



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="完全本地运行的 Wallpaper Engine 图片导出工具。",
    )
    parser.add_argument("input", nargs="?", help="输入路径：单个 .pkg/.tex 文件，或包含它们的文件夹")
    parser.add_argument("output", nargs="?", help="输出目录")
    parser.add_argument("--same-folder", action="store_true", help="把所有导出结果直接放进同一个输出目录")
    parser.add_argument("--nogui", action="store_true", help="禁止自动启动 GUI，仅使用命令行模式")
    parser.add_argument("--self-check", action="store_true", help="检查运行环境与依赖是否可用")
    return parser



def print_stats(stats: Stats) -> None:
    print("")
    print("处理完成")
    print(f"总计：{stats.total}")
    print(f"成功：{stats.success}")
    print(f"跳过：{stats.skipped}")
    print(f"失败：{stats.failed}")



def run_self_check() -> int:
    print(f"{APP_NAME} 自检")
    print("- 运行模式：本地离线")
    print(f"- Python：{sys.version.split()[0]}")
    try:
        import PIL  # noqa: F401
        print("- Pillow：可用")
    except Exception as e:
        print(f"- Pillow：不可用 ({e})")
        return 1

    try:
        import lz4  # noqa: F401
        print("- lz4：可用")
    except Exception as e:
        print(f"- lz4：不可用 ({e})")
        return 1

    print("- 自检完成：环境正常")
    return 0



def run_cli(input_arg: str, output_arg: str, same_folder: bool = False) -> int:
    input_path = Path(input_arg).expanduser()
    out_dir = Path(output_arg).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    estimated = count_exportable_items(input_path) if input_path.exists() else 0
    if estimated:
        print(f"发现待处理项目：{estimated}")
    print(f"输出模式：{'同一文件夹' if same_folder else '简化目录'}")

    try:
        stats = process_input(input_path, out_dir, same_folder=same_folder)
    except CancelledError as e:
        print(f"已取消：{e}")
        return 130

    print_stats(stats)
    return 0 if stats.failed == 0 else 2



def launch_gui() -> int:
    try:
        from gui import launch

        launch()
        return 0
    except Exception as e:
        print(f"GUI 启动失败：{e}")
        print("你仍然可以使用命令行模式：")
        print('  python main.py "输入路径" "输出目录"')
        return 1



def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.self_check:
        return run_self_check()

    if args.input and args.output:
        return run_cli(args.input, args.output, same_folder=args.same_folder)

    if args.nogui:
        parser.print_help()
        return 0

    return launch_gui()


if __name__ == "__main__":
    raise SystemExit(main())
