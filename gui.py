import queue
import threading
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.extractor import CancelledError, count_exportable_items, process_input
from app.local_state import get_app_dir, load_settings, save_settings

PROJECT_LINK_TEXT = "Wallpaper-Unpacker-GUI"
PROJECT_LINK_URL = "https://github.com/li-mao-mao/wallpaper-unpacker-gui"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Wallpaper-Unpacker-GUI")
        self.resize(1180, 780)
        self.setMinimumSize(900, 620)

        self.settings = load_settings()
        self.running = False
        self.cancel_requested = False
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.done_queue: "queue.Queue[tuple]" = queue.Queue()
        self.progress_queue: "queue.Queue[dict]" = queue.Queue()
        self.estimate_queue: "queue.Queue[int | str]" = queue.Queue()

        self._build_ui()
        self._apply_styles()
        self._update_output_rule_text()
        self._refresh_estimate_async()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_queues)
        self.poll_timer.start(80)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        title = QLabel("Wallpaper-Unpacker-GUI")
        title.setObjectName("title")
        subtitle = QLabel("一个让用户能够轻松从 Wallpaper Engine 壁纸包（.pkg / .tex）中提取原始图片的图形化工具")
        subtitle.setObjectName("subtitle")
        link = QLabel(f'<a href="{PROJECT_LINK_URL}">{PROJECT_LINK_TEXT}</a>')
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignmentFlag.AlignRight)
        link.setObjectName("link")
        top_row = QHBoxLayout()
        top_row.addWidget(title, 1)
        top_row.addWidget(link)
        outer.addLayout(top_row)
        outer.addWidget(subtitle)

        form_box = QGroupBox("路径与选项")
        form_layout = QGridLayout(form_box)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(10)
        outer.addWidget(form_box)

        self.input_edit = QLineEdit(self.settings.get("last_input", ""))
        self.output_edit = QLineEdit(self.settings.get("last_output", ""))
        form_layout.addWidget(QLabel("输入路径"), 0, 0)
        form_layout.addWidget(self.input_edit, 0, 1)
        btn_in_file = QPushButton("选文件")
        btn_in_dir = QPushButton("选文件夹")
        in_actions = QHBoxLayout()
        in_actions.addWidget(btn_in_file)
        in_actions.addWidget(btn_in_dir)
        in_wrap = QWidget()
        in_wrap.setLayout(in_actions)
        form_layout.addWidget(in_wrap, 0, 2)

        form_layout.addWidget(QLabel("输出目录"), 1, 0)
        form_layout.addWidget(self.output_edit, 1, 1)
        btn_out_pick = QPushButton("选择输出")
        btn_out_open = QPushButton("打开输出")
        out_actions = QHBoxLayout()
        out_actions.addWidget(btn_out_pick)
        out_actions.addWidget(btn_out_open)
        out_wrap = QWidget()
        out_wrap.setLayout(out_actions)
        form_layout.addWidget(out_wrap, 1, 2)

        self.same_folder_checkbox = QCheckBox("导出结果全部放进同一个文件夹")
        self.same_folder_checkbox.setChecked(bool(self.settings.get("same_folder_output", False)))
        self.auto_open_checkbox = QCheckBox("完成后自动打开输出目录")
        self.auto_open_checkbox.setChecked(bool(self.settings.get("auto_open_output", False)))
        option_row = QHBoxLayout()
        option_row.addWidget(self.same_folder_checkbox)
        option_row.addWidget(self.auto_open_checkbox)
        option_row.addStretch(1)
        option_wrap = QWidget()
        option_wrap.setLayout(option_row)
        form_layout.addWidget(option_wrap, 2, 0, 1, 3)

        self.output_rule_label = QLabel("")
        self.output_rule_label.setWordWrap(True)
        form_layout.addWidget(self.output_rule_label, 3, 0, 1, 3)

        toolbar = QHBoxLayout()
        outer.addLayout(toolbar)
        btn_start = QPushButton("开始导出")
        btn_stop = QPushButton("停止")
        btn_clear = QPushButton("清空日志")
        btn_open_app = QPushButton("打开本地运行目录")
        self.status_label = QLabel("就绪")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        toolbar.addWidget(btn_start)
        toolbar.addWidget(btn_stop)
        toolbar.addWidget(btn_clear)
        toolbar.addWidget(btn_open_app)
        toolbar.addStretch(1)
        toolbar.addWidget(self.status_label)

        self.progress_text_label = QLabel("等待开始")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        outer.addWidget(self.progress_text_label)
        outer.addWidget(self.progress_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        splitter.addWidget(left_panel)

        stats_group = QGroupBox("运行概览")
        stats_layout = QGridLayout(stats_group)
        left_layout.addWidget(stats_group)
        self.estimated_total_label = QLabel("0")
        self.summary_total_label = QLabel("0")
        self.summary_success_label = QLabel("0")
        self.summary_skipped_label = QLabel("0")
        self.summary_failed_label = QLabel("0")
        self.last_run_label = QLabel(self.settings.get("last_run_time", "尚未运行"))
        self.local_path_label = QLabel(str(get_app_dir()))
        self.local_path_label.setWordWrap(True)

        stats_layout.addWidget(QLabel("预计任务"), 0, 0)
        stats_layout.addWidget(self.estimated_total_label, 0, 1)
        stats_layout.addWidget(QLabel("总计"), 1, 0)
        stats_layout.addWidget(self.summary_total_label, 1, 1)
        stats_layout.addWidget(QLabel("成功"), 2, 0)
        stats_layout.addWidget(self.summary_success_label, 2, 1)
        stats_layout.addWidget(QLabel("跳过"), 3, 0)
        stats_layout.addWidget(self.summary_skipped_label, 3, 1)
        stats_layout.addWidget(QLabel("失败"), 4, 0)
        stats_layout.addWidget(self.summary_failed_label, 4, 1)

        local_group = QGroupBox("本地化说明")
        local_layout = QVBoxLayout(local_group)
        local_layout.addWidget(QLabel("本工具完全本地运行，不会上传任何数据。"))
        local_layout.addWidget(self.local_path_label)
        left_layout.addWidget(local_group)

        run_group = QGroupBox("最近运行")
        run_layout = QVBoxLayout(run_group)
        run_layout.addWidget(self.last_run_label)
        left_layout.addWidget(run_group)
        left_layout.addStretch(1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        splitter.addWidget(right_panel)

        right_layout.addWidget(QLabel("处理日志"))
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        fixed_font = QFont("Consolas")
        fixed_font.setPointSize(10)
        self.log_text.setFont(fixed_font)
        self.log_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout.addWidget(self.log_text, 1)
        self._append_log("欢迎使用。本工具完全离线运行，日志与配置仅存本机。")

        splitter.setSizes([290, 860])

        self.input_edit.textChanged.connect(self._on_path_changed)
        self.output_edit.textChanged.connect(self._persist_settings)
        self.same_folder_checkbox.stateChanged.connect(self._on_same_folder_changed)
        self.auto_open_checkbox.stateChanged.connect(self._persist_settings)
        btn_in_file.clicked.connect(self.pick_input_file)
        btn_in_dir.clicked.connect(self.pick_input_dir)
        btn_out_pick.clicked.connect(self.pick_output_dir)
        btn_out_open.clicked.connect(self.open_output_dir)
        btn_start.clicked.connect(self.start_extract)
        btn_stop.clicked.connect(self.request_cancel)
        btn_clear.clicked.connect(self.clear_log)
        btn_open_app.clicked.connect(self.open_app_dir)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #eef3fb; color: #0f172a; font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
            QGroupBox { border: 1px solid #dbe3f3; border-radius: 8px; margin-top: 10px; background: #ffffff; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #334155; font-weight: 600; }
            QLineEdit, QPlainTextEdit { background: #ffffff; border: 1px solid #cfd7e7; border-radius: 6px; padding: 6px; }
            QPushButton { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { border-color: #94a3b8; }
            QProgressBar { border: 1px solid #cfd7e7; border-radius: 6px; text-align: center; background: #ffffff; min-height: 20px; }
            QProgressBar::chunk { background: #2563eb; border-radius: 5px; }
            QLabel#title { font-size: 24px; font-weight: 700; }
            QLabel#subtitle { color: #475569; }
            QLabel#link { color: #2563eb; }
            """
        )

    def _on_path_changed(self) -> None:
        self._persist_settings()
        self._refresh_estimate_async()

    def _on_same_folder_changed(self) -> None:
        self._update_output_rule_text()
        self._persist_settings()

    def _update_output_rule_text(self) -> None:
        if self.same_folder_checkbox.isChecked():
            self.output_rule_label.setText("当前规则：所有导出图片都会直接进入你选择的输出目录，不额外套文件夹。")
        else:
            self.output_rule_label.setText("当前规则：TEX直接输出到目标目录，PKG只保留一层包名文件夹。")

    def _persist_settings(self) -> None:
        save_settings(
            {
                "last_input": self.input_edit.text().strip(),
                "last_output": self.output_edit.text().strip(),
                "same_folder_output": self.same_folder_checkbox.isChecked(),
                "auto_open_output": self.auto_open_checkbox.isChecked(),
                "last_run_time": self.last_run_label.text(),
            }
        )

    def _refresh_estimate_async(self) -> None:
        input_path = self.input_edit.text().strip()
        if not input_path:
            self.estimated_total_label.setText("0")
            return

        def worker() -> None:
            try:
                source = Path(input_path).expanduser()
                total = count_exportable_items(source) if source.exists() else 0
                self.estimate_queue.put(total)
            except Exception:
                self.estimate_queue.put("?")

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queues(self) -> None:
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(msg)

        while True:
            try:
                payload = self.progress_queue.get_nowait()
            except queue.Empty:
                break
            self._apply_progress(payload)

        while True:
            try:
                estimated = self.estimate_queue.get_nowait()
            except queue.Empty:
                break
            self.estimated_total_label.setText(str(estimated))

        try:
            kind, payload = self.done_queue.get_nowait()
        except queue.Empty:
            return

        if kind == "done":
            stats = payload
            self.summary_total_label.setText(str(stats.total))
            self.summary_success_label.setText(str(stats.success))
            self.summary_skipped_label.setText(str(stats.skipped))
            self.summary_failed_label.setText(str(stats.failed))
            self.status_label.setText("处理完成")
            self.progress_text_label.setText(f"完成：{stats.processed}/{stats.total} 项")
            self.progress_bar.setValue(100 if stats.total else 0)
            self.last_run_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self._persist_settings()
            if self.auto_open_checkbox.isChecked():
                self.open_output_dir()
        elif kind == "cancelled":
            self.status_label.setText("已取消")
            self.progress_text_label.setText("任务已停止")
            self._append_log(str(payload))
        else:
            self.status_label.setText("处理失败")
            self._append_log(f"失败：{payload}")
            QMessageBox.critical(self, "处理失败", str(payload))
        self._finish_extract()

    def _apply_progress(self, payload: dict) -> None:
        total = int(payload.get("total", 0) or 0)
        processed = int(payload.get("processed", 0) or 0)
        detail = str(payload.get("detail", ""))
        event = payload.get("event")

        shown_total = total
        if shown_total <= 0:
            try:
                shown_total = int(self.estimated_total_label.text())
            except ValueError:
                shown_total = 0

        if shown_total > 0:
            self.progress_bar.setValue(min(100, int(processed / shown_total * 100)))
        if event == "item_start" and detail:
            self.progress_text_label.setText(f"处理中：{processed}/{shown_total or '?'} · {detail}")
        elif event == "item_done":
            self.progress_text_label.setText(f"已完成：{processed}/{shown_total or '?'}")

    def _append_log(self, text: str) -> None:
        self.log_text.appendPlainText(text)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def clear_log(self) -> None:
        if self.running:
            return
        self.log_text.clear()
        self._append_log("日志已清空。")
        self.status_label.setText("就绪")
        self.progress_text_label.setText("等待开始")
        self.progress_bar.setValue(0)
        self.summary_total_label.setText("0")
        self.summary_success_label.setText("0")
        self.summary_skipped_label.setText("0")
        self.summary_failed_label.setText("0")

    def pick_input_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择输入文件", "", "Package/Tex 文件 (*.pkg *.tex);;所有文件 (*.*)")
        if path:
            self.input_edit.setText(path)

    def pick_input_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输入文件夹")
        if path:
            self.input_edit.setText(path)

    def pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.output_edit.setText(path)

    def _open_path(self, path: Path) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "打开失败", f"无法打开路径：{path}")

    def open_app_dir(self) -> None:
        self._open_path(get_app_dir())

    def open_output_dir(self) -> None:
        path_text = self.output_edit.text().strip()
        if not path_text:
            return
        output_path = Path(path_text)
        if not output_path.exists():
            QMessageBox.information(self, "提示", "输出目录还不存在，请先运行一次导出。")
            return
        self._open_path(output_path)

    def request_cancel(self) -> None:
        if not self.running:
            return
        self.cancel_requested = True
        self.status_label.setText("正在停止…")
        self._append_log("收到停止请求，正在等待当前文件处理结束…")

    def start_extract(self) -> None:
        if self.running:
            return
        input_path = self.input_edit.text().strip()
        output_dir = self.output_edit.text().strip()
        if not input_path or not output_dir:
            QMessageBox.critical(self, "错误", "请先选择输入路径和输出目录")
            return

        source = Path(input_path).expanduser()
        out_dir = Path(output_dir).expanduser()
        if not source.exists():
            QMessageBox.critical(self, "错误", "输入路径不存在")
            return

        self.clear_log()
        self.cancel_requested = False
        self.running = True
        self.status_label.setText("处理中…")
        self.progress_text_label.setText("正在准备任务…")
        self.progress_bar.setValue(0)
        self._persist_settings()

        threading.Thread(target=self._worker, args=(str(source), str(out_dir), self.same_folder_checkbox.isChecked()), daemon=True).start()

    def _worker(self, input_path: str, output_dir: str, same_folder: bool) -> None:
        try:
            source = Path(input_path)
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            estimated = count_exportable_items(source)
            self.estimate_queue.put(estimated)
            self.log_queue.put(f"开始处理：{source}")
            self.log_queue.put(f"预计任务数：{estimated}")
            self.log_queue.put("输出模式：同一文件夹" if same_folder else "输出模式：简化目录")
            stats = process_input(
                source,
                out,
                logger=self.log_queue.put,
                progress_callback=self.progress_queue.put,
                cancel_requested=lambda: self.cancel_requested,
                same_folder=same_folder,
            )
            self.done_queue.put(("done", stats))
        except CancelledError as e:
            self.done_queue.put(("cancelled", e))
        except Exception as e:
            self.done_queue.put(("error", e))

    def _finish_extract(self) -> None:
        self.running = False
        self.cancel_requested = False


def launch() -> None:
    app = QApplication.instance()
    created = app is None
    if app is None:
        app = QApplication([])
    window = MainWindow()
    window.show()
    if created:
        app.exec()


if __name__ == "__main__":
    launch()
