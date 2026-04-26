import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from .pkg_reader import read_pkg
from .tex_reader import read_tex
from .tex_convert import convert_tex

Logger = Optional[Callable[[str], None]]
ProgressCallback = Optional[Callable[[dict], None]]
CancelCheck = Optional[Callable[[], bool]]


@dataclass
class Stats:
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def processed(self) -> int:
        return self.success + self.skipped + self.failed


@dataclass
class RunRecord:
    source: str
    target: str
    status: str
    category: str
    detail: str


class CancelledError(RuntimeError):
    pass



def log(logger: Logger, message: str) -> None:
    if logger:
        logger(message)
    else:
        print(message)



def emit_progress(progress_callback: ProgressCallback, **payload: object) -> None:
    if progress_callback:
        progress_callback(payload)



def ensure_not_cancelled(cancel_requested: CancelCheck) -> None:
    if cancel_requested and cancel_requested():
        raise CancelledError("用户已取消本次导出")



def unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 1
    while True:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1



def sanitize_relative_path(path_str: str) -> Path:
    text = (path_str or "").replace("\\", "/").strip("/")
    parts = []
    for part in text.split("/"):
        if not part or part in (".", ".."):
            continue
        safe = part.replace(":", "_").strip()
        parts.append(safe or "unnamed")
    if not parts:
        return Path("unnamed.tex")
    return Path(*parts)



def flatten_path_name(path_value: Path | str, keep_suffix: bool = False) -> str:
    path_obj = sanitize_relative_path(str(path_value))
    if not keep_suffix:
        path_obj = path_obj.with_suffix("")
    parts = [part for part in path_obj.parts if part not in ("", ".")]
    return "__".join(parts) if parts else "unnamed"



def build_pkg_label(pkg_path: Path, input_root: Optional[Path]) -> str:
    if input_root is not None:
        try:
            rel = pkg_path.relative_to(input_root)
            return flatten_path_name(rel)
        except Exception:
            pass
    return flatten_path_name(pkg_path.name)



def build_tex_label(tex_path: Path, input_root: Optional[Path]) -> str:
    if input_root is not None:
        try:
            rel = tex_path.relative_to(input_root)
            return flatten_path_name(rel)
        except Exception:
            pass
    return flatten_path_name(tex_path.name)



def export_tex_bytes(tex_bytes: bytes, output_base_path: Path) -> str:
    tex = read_tex(tex_bytes)
    converted = convert_tex(tex, preserve_embedded_formats=True)

    if converted.kind == "skip":
        return f"skip_{converted.reason}"

    output_path = unique_output_path(output_base_path.with_suffix(converted.ext))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if converted.kind == "bytes":
        output_path.write_bytes(converted.data)
    elif converted.kind == "image":
        converted.image.save(output_path)
    else:
        raise ValueError(f"未知导出结果类型: {converted.kind}")

    return str(output_path)



def count_exportable_items(input_path: Path) -> int:
    input_path = input_path.resolve()
    if input_path.is_file():
        if input_path.suffix.lower() == ".tex":
            return 1
        if input_path.suffix.lower() == ".pkg":
            pkg = read_pkg(input_path.read_bytes(), read_entry_bytes=False)
            return sum(1 for entry in pkg.entries if entry.full_path.lower().endswith(".tex"))
        return 0

    total = 0
    for path in scan_inputs(input_path):
        if path.suffix.lower() == ".tex":
            total += 1
        elif path.suffix.lower() == ".pkg":
            pkg = read_pkg(path.read_bytes(), read_entry_bytes=False)
            total += sum(1 for entry in pkg.entries if entry.full_path.lower().endswith(".tex"))
    return total



def _handle_result(
    *,
    result: str,
    stats: Stats,
    records: List[RunRecord],
    source_label: str,
    category: str,
    detail: str,
    logger: Logger,
    progress_callback: ProgressCallback,
) -> None:
    if result == "skip_video":
        stats.skipped += 1
        records.append(RunRecord(source=source_label, target="", status="skipped", category=category, detail="视频纹理"))
        log(logger, f"[跳过][视频纹理] {detail}")
    elif result == "skip_gif":
        stats.skipped += 1
        records.append(RunRecord(source=source_label, target="", status="skipped", category=category, detail="GIF 纹理"))
        log(logger, f"[跳过][GIF纹理] {detail}")
    else:
        stats.success += 1
        records.append(RunRecord(source=source_label, target=result, status="success", category=category, detail=detail))
        log(logger, f"[成功][{category}] {detail} -> {Path(result).name}")

    emit_progress(
        progress_callback,
        event="item_done",
        total=stats.total,
        processed=stats.processed,
        success=stats.success,
        skipped=stats.skipped,
        failed=stats.failed,
    )



def export_pkg_file(
    pkg_path: Path,
    out_root: Path,
    *,
    same_folder: bool = False,
    input_root: Optional[Path] = None,
    logger: Logger = None,
    stats: Optional[Stats] = None,
    progress_callback: ProgressCallback = None,
    cancel_requested: CancelCheck = None,
    records: Optional[List[RunRecord]] = None,
) -> None:
    pkg = read_pkg(pkg_path.read_bytes(), read_entry_bytes=True)
    pkg_label = build_pkg_label(pkg_path, input_root)
    pkg_folder = out_root / pkg_label

    for entry in pkg.entries:
        if not entry.full_path.lower().endswith(".tex"):
            continue

        ensure_not_cancelled(cancel_requested)
        entry_label = flatten_path_name(entry.full_path)
        target_base = (out_root / f"{pkg_label}__{entry_label}") if same_folder else (pkg_folder / entry_label)
        if stats:
            stats.total += 1

        emit_progress(
            progress_callback,
            event="item_start",
            total=stats.total,
            processed=stats.processed,
            detail=entry.full_path,
            source=str(pkg_path),
        )

        try:
            result = export_tex_bytes(entry.data, target_base)
            _handle_result(
                result=result,
                stats=stats if stats is not None else Stats(),
                records=records if records is not None else [],
                source_label=f"{pkg_path.name}:{entry.full_path}",
                category="PKG",
                detail=f"{pkg_path.name} -> {entry.full_path}",
                logger=logger,
                progress_callback=progress_callback,
            )
        except Exception as e:
            if stats:
                stats.failed += 1
            if records is not None:
                records.append(RunRecord(source=f"{pkg_path.name}:{entry.full_path}", target="", status="failed", category="PKG", detail=str(e)))
            log(logger, f"[失败][PKG] {pkg_path.name} -> {entry.full_path} | {e}")
            emit_progress(
                progress_callback,
                event="item_done",
                total=stats.total if stats else 0,
                processed=stats.processed if stats else 0,
                success=stats.success if stats else 0,
                skipped=stats.skipped if stats else 0,
                failed=stats.failed if stats else 0,
            )



def export_tex_file(
    tex_path: Path,
    out_base_path: Path,
    logger: Logger = None,
    stats: Optional[Stats] = None,
    progress_callback: ProgressCallback = None,
    records: Optional[List[RunRecord]] = None,
) -> None:
    if stats:
        stats.total += 1

    emit_progress(
        progress_callback,
        event="item_start",
        total=stats.total if stats else 0,
        processed=stats.processed if stats else 0,
        detail=str(tex_path),
        source=str(tex_path),
    )

    try:
        result = export_tex_bytes(tex_path.read_bytes(), out_base_path)
        _handle_result(
            result=result,
            stats=stats if stats is not None else Stats(),
            records=records if records is not None else [],
            source_label=str(tex_path),
            category="TEX",
            detail=str(tex_path),
            logger=logger,
            progress_callback=progress_callback,
        )
    except Exception as e:
        if stats:
            stats.failed += 1
        if records is not None:
            records.append(RunRecord(source=str(tex_path), target="", status="failed", category="TEX", detail=str(e)))
        log(logger, f"[失败][TEX] {tex_path} | {e}")
        emit_progress(
            progress_callback,
            event="item_done",
            total=stats.total if stats else 0,
            processed=stats.processed if stats else 0,
            success=stats.success if stats else 0,
            skipped=stats.skipped if stats else 0,
            failed=stats.failed if stats else 0,
        )



def scan_inputs(input_path: Path) -> Iterable[Path]:
    if input_path.is_file():
        yield input_path
        return

    for path in sorted(input_path.rglob("*")):
        if path.is_file() and path.suffix.lower() in (".pkg", ".tex"):
            yield path



def write_manifest(manifest_path: Path, input_path: Path, out_root: Path, stats: Stats, records: List[RunRecord]) -> Path:
    manifest = {
        "app": "Wallpaper-Unpacker-GUI",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "input_path": str(input_path),
        "output_dir": str(out_root),
        "stats": asdict(stats),
        "records": [asdict(record) for record in records],
        "local_only": True,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path



def process_input(
    input_path: Path,
    out_root: Path,
    logger: Logger = None,
    progress_callback: ProgressCallback = None,
    cancel_requested: CancelCheck = None,
    manifest_path: Optional[Path] = None,
    same_folder: bool = False,
) -> Stats:
    stats = Stats()
    records: List[RunRecord] = []
    input_path = input_path.resolve()
    out_root = out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    if input_path.is_file():
        if input_path.suffix.lower() == ".pkg":
            export_pkg_file(
                input_path,
                out_root,
                same_folder=same_folder,
                logger=logger,
                stats=stats,
                progress_callback=progress_callback,
                cancel_requested=cancel_requested,
                records=records,
            )
        elif input_path.suffix.lower() == ".tex":
            export_tex_file(
                input_path,
                out_root / build_tex_label(input_path, None),
                logger=logger,
                stats=stats,
                progress_callback=progress_callback,
                records=records,
            )
        else:
            raise ValueError("输入必须是 .pkg / .tex 文件，或包含它们的文件夹")
        if manifest_path:
            write_manifest(manifest_path, input_path, out_root, stats, records)
        return stats

    if not input_path.is_dir():
        raise ValueError("输入路径不存在，或既不是文件也不是文件夹")

    files = list(scan_inputs(input_path))
    if not files:
        raise ValueError("输入文件夹中没有找到 .pkg 或 .tex 文件")

    for file_path in files:
        ensure_not_cancelled(cancel_requested)
        if file_path.suffix.lower() == ".pkg":
            export_pkg_file(
                file_path,
                out_root,
                same_folder=same_folder,
                input_root=input_path,
                logger=logger,
                stats=stats,
                progress_callback=progress_callback,
                cancel_requested=cancel_requested,
                records=records,
            )
        else:
            out_base_path = out_root / build_tex_label(file_path, input_path)
            export_tex_file(
                file_path,
                out_base_path,
                logger=logger,
                stats=stats,
                progress_callback=progress_callback,
                records=records,
            )

    if manifest_path:
        write_manifest(manifest_path, input_path, out_root, stats, records)

    return stats
