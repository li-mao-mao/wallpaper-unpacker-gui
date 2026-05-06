import queue
import threading
import json
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.extractor import CancelledError, count_exportable_items, process_input
from app.local_state import load_settings, save_settings

PROJECT_LINK_URL = "https://github.com/li-mao-mao/wallpaper-unpacker-gui"
DOCS_LINK_URL = "https://github.com/li-mao-mao/wallpaper-unpacker-gui/blob/main/README_zh.md"
APP_VERSION = "v1.2.0"


def load_icons() -> dict[str, str]:
    icon_path = Path(__file__).with_name("icons.json")
    try:
        return json.loads(icon_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Wallpaper-Unpacker-GUI")
        self.resize(1540, 1000)
        self.setMinimumSize(1100, 720)

        self.settings = load_settings()
        self.running = False
        self.cancel_requested = False
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.done_queue: "queue.Queue[tuple]" = queue.Queue()
        self.progress_queue: "queue.Queue[dict]" = queue.Queue()
        self.estimate_queue: "queue.Queue[int | str]" = queue.Queue()
        self.icons = load_icons()

        self._build_ui()
        self._apply_styles()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_queues)
        self.poll_timer.start(80)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        shell = QHBoxLayout(root)
        shell.setContentsMargins(24, 28, 24, 24)
        shell.setSpacing(24)

        shell.addWidget(self._build_sidebar())
        shell.addLayout(self._build_main_area(), 1)

        self.input_edit.textChanged.connect(self._on_path_changed)
        self.output_edit.textChanged.connect(self._persist_settings)

        self._append_log("欢迎使用 Wallpaper-Unpacker-GUI!")
        self._append_log("本工具完全离线运行，日志与配置仅存本机。")

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(228)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 22, 0, 0)
        layout.setSpacing(18)

        logo = QLabel(self.icon("app_logo"))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setObjectName("logo")
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)

        run_card = self._side_card()
        run_layout = QVBoxLayout(run_card)
        run_layout.setContentsMargins(18, 18, 18, 18)
        run_layout.setSpacing(14)
        run_layout.addWidget(self._side_title("运行概览"))
        self.estimated_total_label = self._stat_row(run_layout, "预计任务", "0", "green")
        self.summary_total_label = self._stat_row(run_layout, "总计", "0", "blue")
        self.summary_success_label = self._stat_row(run_layout, "成功", "0", "lime")
        self.summary_skipped_label = self._stat_row(run_layout, "跳过", "0", "orange")
        self.summary_failed_label = self._stat_row(run_layout, "失败", "0", "red")
        layout.addWidget(run_card)

        recent_card = self._side_card()
        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(18, 18, 18, 18)
        recent_layout.setSpacing(12)
        recent_layout.addWidget(self._side_title("最近运行"))
        self.last_run_label = QLabel(self.settings.get("last_run_time") or "尚未运行")
        self.last_run_label.setObjectName("muted")
        recent_layout.addWidget(self.last_run_label)
        layout.addWidget(recent_card)

        layout.addStretch(1)
        footer = QHBoxLayout()
        version = QLabel(APP_VERSION)
        version.setObjectName("versionText")
        footer.addWidget(version)
        footer.addStretch(1)
        layout.addLayout(footer)
        return sidebar

    def _build_main_area(self) -> QVBoxLayout:
        main = QVBoxLayout()
        main.setSpacing(16)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(8)
        title = QLabel("Wallpaper-Unpacker-GUI")
        title.setObjectName("appTitle")
        title_block.addWidget(title)
        header.addLayout(title_block, 1)
        header.addWidget(self._top_action("home", "项目主页", lambda: QDesktopServices.openUrl(QUrl(PROJECT_LINK_URL))))
        header.addWidget(self._top_action("docs", "使用文档", lambda: QDesktopServices.openUrl(QUrl(DOCS_LINK_URL))))
        header.addWidget(self._top_action("info", "关于工具", self._show_about))
        main.addLayout(header)

        path_card = self._card("section", "路径与选项")
        path_layout = path_card.layout()
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(20)
        grid.setColumnStretch(1, 1)
        path_layout.addLayout(grid)

        self.input_edit = QLineEdit(self.settings.get("last_input", ""))
        self.input_edit.setPlaceholderText("请选择或拖拽 .pkg / .tex 文件或文件夹到此处")
        self.output_edit = QLineEdit(self.settings.get("last_output", ""))
        self.output_edit.setPlaceholderText("请选择输出目录")
        self._add_path_row(grid, 0, "输入路径", self.input_edit, [
            ("file", "选文件", self._pick_input_file),
            ("folder", "选文件夹", self._pick_input_dir),
        ])
        self._add_path_row(grid, 1, "输出目录", self.output_edit, [
            ("folder", "选择输出", self._pick_output),
            ("open", "打开输出", self.open_output_dir),
        ])

        option_row = QHBoxLayout()
        self.same_folder_check = QCheckBox("导出结果全部放进同一个文件夹")
        self.same_folder_check.setChecked(bool(self.settings.get("same_folder_output", False)))
        self.same_folder_check.stateChanged.connect(self._same_folder_changed)
        self.auto_open_check = QCheckBox("完成后自动打开输出目录")
        self.auto_open_check.setChecked(bool(self.settings.get("auto_open_output", False)))
        self.auto_open_check.stateChanged.connect(self._auto_open_changed)
        option_row.addWidget(self.same_folder_check)
        option_row.addSpacing(32)
        option_row.addWidget(self.auto_open_check)
        option_row.addStretch(1)
        path_layout.addLayout(option_row)

        main.addWidget(path_card)

        action_row = QHBoxLayout()
        action_row.setSpacing(14)
        self.run_btn = QPushButton(self.text_with_icon("run", "开始导出"))
        self.run_btn.setObjectName("primaryBtn")
        self.run_btn.clicked.connect(self.start_extract)
        self.stop_btn = QPushButton(self.text_with_icon("stop", "停止"))
        self.stop_btn.setObjectName("secondaryBtn")
        self.stop_btn.clicked.connect(self.request_cancel)
        self.clear_btn = QPushButton(self.text_with_icon("clear", "清空日志"))
        self.clear_btn.setObjectName("secondaryBtn")
        self.clear_btn.clicked.connect(self.clear_log)
        for button in [self.run_btn, self.stop_btn, self.clear_btn]:
            button.setFixedHeight(50)
            action_row.addWidget(button)
        action_row.addStretch(1)
        self.status_pill = QLabel(self.text_with_icon("status", "就绪"))
        self.status_pill.setObjectName("statusPill")
        action_row.addWidget(self.status_pill)
        main.addLayout(action_row)

        progress_card = QFrame()
        progress_card.setObjectName("thinCard")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(16, 14, 16, 16)
        progress_layout.setSpacing(8)
        progress_header = QHBoxLayout()
        self.status_label = QLabel("等待开始")
        self.status_label.setObjectName("progressStatus")
        self.progress_percent_label = QLabel("0%")
        self.progress_percent_label.setObjectName("progressPercent")
        progress_header.addWidget(self.status_label)
        progress_header.addStretch(1)
        progress_header.addWidget(self.progress_percent_label)
        progress_layout.addLayout(progress_header)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.progress_bar)
        main.addWidget(progress_card)

        log_card = self._card("section", "处理日志")
        log_layout = log_card.layout()
        log_actions = QHBoxLayout()
        log_actions.addStretch(1)
        btn_export_log = QPushButton(self.text_with_icon("export", "导出日志"))
        btn_export_log.setObjectName("smallBtn")
        btn_export_log.clicked.connect(self.export_log)
        log_actions.addWidget(btn_export_log)
        log_layout.insertLayout(0, log_actions)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Microsoft YaHei UI", 11))
        self.log_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_layout.addWidget(self.log_text, 1)
        main.addWidget(log_card, 1)

        return main

    def icon(self, name: str) -> str:
        return self.icons.get(name, "")

    def text_with_icon(self, icon_name: str, text: str) -> str:
        icon = self.icon(icon_name)
        return f"{icon}  {text}" if icon else text

    def _card(self, icon_name: str, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        heading = QLabel(self.text_with_icon(icon_name, title))
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        return card

    def _side_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("sideCard")
        return card

    def _side_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sideTitle")
        return label

    def _stat_row(self, layout: QVBoxLayout, text: str, value: str, color: str) -> QLabel:
        row = QHBoxLayout()
        dot = QLabel(self.icon("status"))
        dot.setObjectName(f"dot_{color}")
        label = QLabel(text)
        label.setObjectName("statName")
        number = QLabel(value)
        number.setObjectName("statValue")
        row.addWidget(dot)
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(number)
        layout.addLayout(row)
        return number

    def _top_action(self, icon_name: str, text: str, callback) -> QPushButton:
        icon = self.icon(icon_name)
        button = QPushButton(f"{icon}\n{text}" if icon else text)
        button.setObjectName("topAction")
        button.setFixedSize(112, 88)
        button.clicked.connect(callback)
        return button

    def _add_path_row(self, grid: QGridLayout, row: int, label_text: str, edit: QLineEdit, buttons: list[tuple[str, str, object]]) -> None:
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        edit.setObjectName("pathInput")
        edit.setMinimumHeight(48)
        grid.addWidget(label, row, 0)
        grid.addWidget(edit, row, 1)
        button_box = QHBoxLayout()
        button_box.setSpacing(14)
        for icon_name, text, callback in buttons:
            button = QPushButton(self.text_with_icon(icon_name, text))
            button.setObjectName("pathBtn")
            button.setFixedHeight(48)
            button.clicked.connect(callback)
            button_box.addWidget(button)
        grid.addLayout(button_box, row, 2)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#root {
                background: #f7f9ff;
                color: #111827;
                font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
                font-size: 14px;
            }
            QWidget#sidebar {
                background: transparent;
            }
            QLabel#logo {
                min-width: 110px;
                min-height: 110px;
                max-width: 110px;
                max-height: 110px;
                background: #ffffff;
                border: 1px solid #e6eaf5;
                border-radius: 16px;
                color: #5b6ee8;
                font-size: 50px;
                font-weight: 700;
            }
            QFrame#sideCard, QFrame#card, QFrame#thinCard {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
            }
            QLabel#sideTitle, QLabel#cardTitle {
                color: #111827;
                font-weight: 800;
            }
            QLabel#sideTitle {
                font-size: 15px;
            }
            QLabel#cardTitle {
                font-size: 17px;
            }
            QLabel#muted {
                color: #657083;
                line-height: 150%;
            }
            QLabel#versionText {
                color: #657083;
                padding-left: 8px;
            }
            QLabel#appTitle {
                font-size: 32px;
                font-weight: 800;
                color: #111827;
            }
            QPushButton#topAction {
                background: #f4f7fc;
                border: 1px solid #dce3ef;
                border-radius: 10px;
                color: #111827;
                font-size: 15px;
                font-weight: 700;
            }
            QPushButton#topAction:hover, QPushButton#pathBtn:hover, QPushButton#secondaryBtn:hover, QPushButton#smallBtn:hover {
                border-color: #7b8cf5;
                background: #f8fbff;
            }
            QLabel#fieldLabel {
                color: #111827;
                font-size: 16px;
                font-weight: 800;
            }
            QLineEdit#pathInput {
                background: #ffffff;
                border: 1px solid #d7deeb;
                border-radius: 8px;
                color: #111827;
                padding: 0 12px;
                selection-background-color: #c7d2fe;
            }
            QLineEdit#pathInput:focus {
                border-color: #6875f5;
            }
            QLineEdit#pathInput::placeholder {
                color: #94a3b8;
            }
            QPushButton#pathBtn, QPushButton#secondaryBtn, QPushButton#smallBtn {
                background: #ffffff;
                border: 1px solid #d7deeb;
                border-radius: 8px;
                color: #1f2937;
                font-weight: 650;
                padding: 0 18px;
            }
            QPushButton#primaryBtn {
                background: #5567e9;
                border: 1px solid #5567e9;
                border-radius: 9px;
                color: #ffffff;
                font-size: 15px;
                font-weight: 800;
                padding: 0 24px;
            }
            QPushButton#primaryBtn:hover {
                background: #4758db;
            }
            QPushButton#secondaryBtn:disabled {
                color: #9aa4b2;
                background: #f6f8fb;
            }
            QCheckBox {
                color: #334155;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border: 1px solid #bcc6d6;
                border-radius: 5px;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #5b6ee8;
                border-color: #5b6ee8;
            }
            QLabel#statusPill {
                background: #f6f8fb;
                border: 1px solid #e4e9f2;
                border-radius: 20px;
                color: #334155;
                padding: 10px 18px;
            }
            QLabel#progressStatus, QLabel#progressPercent {
                color: #1f2937;
                font-size: 14px;
            }
            QProgressBar {
                background: #e2e7f0;
                border: none;
                border-radius: 6px;
                height: 12px;
            }
            QProgressBar::chunk {
                background: #5867e8;
                border-radius: 6px;
            }
            QPlainTextEdit {
                background: #ffffff;
                border: 1px solid #d7deeb;
                border-radius: 8px;
                color: #1f2937;
                padding: 10px;
                selection-background-color: #c7d2fe;
            }
            QLabel#statName {
                color: #475569;
                font-size: 14px;
            }
            QLabel#statValue {
                color: #111827;
                font-size: 14px;
                font-weight: 800;
            }
            QLabel#dot_green { color: #35c276; }
            QLabel#dot_blue { color: #3b82f6; }
            QLabel#dot_lime { color: #79c64f; }
            QLabel#dot_orange { color: #f5a142; }
            QLabel#dot_red { color: #ef5555; }
            """
        )

    def _on_path_changed(self) -> None:
        self._persist_settings()
        self._refresh_estimate_async(silent=True)

    def _persist_settings(self) -> None:
        save_settings(
            {
                "last_input": self.input_edit.text().strip(),
                "last_output": self.output_edit.text().strip(),
                "same_folder_output": bool(self.settings.get("same_folder_output", False)),
                "auto_open_output": bool(self.settings.get("auto_open_output", False)),
                "last_run_time": self.settings.get("last_run_time", ""),
            }
        )

    def _same_folder_changed(self) -> None:
        self.settings["same_folder_output"] = self.same_folder_check.isChecked()
        self._persist_settings()

    def _auto_open_changed(self) -> None:
        self.settings["auto_open_output"] = self.auto_open_check.isChecked()
        self._persist_settings()

    def _refresh_estimate_async(self, silent: bool = False) -> None:
        input_path = self.input_edit.text().strip()
        if not input_path:
            if not silent:
                self._append_log("请先选择输入路径。")
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
            self.estimated_total_label.setText(str(stats.total))
            self.summary_total_label.setText(str(stats.total))
            self.summary_success_label.setText(str(stats.success))
            self.summary_skipped_label.setText(str(stats.skipped))
            self.summary_failed_label.setText(str(stats.failed))
            self.status_label.setText("处理完成")
            self.status_pill.setText(self.text_with_icon("status", "完成"))
            self.progress_bar.setValue(100 if stats.total else 0)
            self.progress_percent_label.setText("100%" if stats.total else "0%")
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.settings["last_run_time"] = now
            self.last_run_label.setText(now)
            self._persist_settings()
            self._append_log(f"处理完成。总计:{stats.total} 成功:{stats.success} 跳过:{stats.skipped} 失败:{stats.failed}")
            if self.settings.get("auto_open_output", False):
                self.open_output_dir()
        elif kind == "cancelled":
            self.status_label.setText("已取消")
            self.status_pill.setText(self.text_with_icon("status", "已取消"))
            self._append_log(str(payload))
        else:
            self.status_label.setText("出错")
            self.status_pill.setText(self.text_with_icon("status", "出错"))
            self._append_log(f"错误: {payload}")
            QMessageBox.critical(self, "错误", str(payload))
        self._finish_extract()

    def _apply_progress(self, payload: dict) -> None:
        total = int(payload.get("total", 0) or 0)
        processed = int(payload.get("processed", 0) or 0)
        detail = str(payload.get("detail", ""))
        event = payload.get("event")

        if total > 0:
            value = min(100, int(processed / total * 100))
            self.progress_bar.setValue(value)
            self.progress_percent_label.setText(f"{value}%")
        if event == "item_start" and detail:
            self.status_label.setText(f"处理中：{processed}/{total or '?'} - {detail}")
        elif event == "item_done":
            self.status_label.setText(f"已完成：{processed}/{total or '?'}")

    def _append_log(self, text: str) -> None:
        self.log_text.appendPlainText(text)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def clear_log(self) -> None:
        if self.running:
            return
        self.log_text.clear()
        self._append_log("日志已清空。")
        self.status_label.setText("等待开始")
        self.status_pill.setText(self.text_with_icon("status", "就绪"))
        self.progress_bar.setValue(0)
        self.progress_percent_label.setText("0%")
        self.estimated_total_label.setText("0")
        self.summary_total_label.setText("0")
        self.summary_success_label.setText("0")
        self.summary_skipped_label.setText("0")
        self.summary_failed_label.setText("0")

    def export_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", "wallpaper-unpacker-log.txt", "Text Files (*.txt);;All Files (*)")
        if not path:
            return
        try:
            Path(path).write_text(self.log_text.toPlainText(), encoding="utf-8")
            self._append_log(f"日志已导出：{path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"日志导出失败：{e}")

    def _pick_input_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择输入文件", "", "PKG/TEX (*.pkg *.tex);;All Files (*)")
        if path:
            self.input_edit.setText(path)

    def _pick_input_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输入文件夹")
        if path:
            self.input_edit.setText(path)

    def _pick_input(self) -> None:
        self._pick_input_dir()

    def _pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.output_edit.setText(path)

    def _open_path(self, path: Path) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "失败", f"无法打开：{path}")

    def open_output_dir(self) -> None:
        path_text = self.output_edit.text().strip()
        if not path_text:
            return
        output_path = Path(path_text)
        if not output_path.exists():
            QMessageBox.information(self, "提示", "输出目录尚不存在。")
            return
        self._open_path(output_path)

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "关于工具",
            f"Wallpaper-Unpacker-GUI {APP_VERSION}\n\n"
            "用于从 Wallpaper Engine 的 .pkg / .tex 文件中提取原始图片。\n"
            "工具完全本地运行，不会上传任何数据。",
        )

    def request_cancel(self) -> None:
        if not self.running:
            return
        self.cancel_requested = True
        self.status_label.setText("正在停止...")
        self.status_pill.setText(self.text_with_icon("status", "停止中"))
        self._append_log("已请求停止，等待当前文件处理结束...")

    def start_extract(self) -> None:
        if self.running:
            return
        input_path = self.input_edit.text().strip()
        output_dir = self.output_edit.text().strip()
        if not input_path or not output_dir:
            QMessageBox.critical(self, "错误", "请选择输入路径和输出目录。")
            return

        source = Path(input_path).expanduser()
        out_dir = Path(output_dir).expanduser()
        if not source.exists():
            QMessageBox.critical(self, "错误", "输入路径不存在。")
            return

        self.clear_log()
        self.cancel_requested = False
        self.running = True
        self.status_label.setText("正在运行...")
        self.status_pill.setText(self.text_with_icon("status", "运行中"))
        self.progress_bar.setValue(0)
        self.progress_percent_label.setText("0%")
        self._persist_settings()

        same_folder = self.settings.get("same_folder_output", False)
        threading.Thread(target=self._worker, args=(str(source), str(out_dir), same_folder), daemon=True).start()

    def _worker(self, input_path: str, output_dir: str, same_folder: bool) -> None:
        try:
            source = Path(input_path)
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            estimated = count_exportable_items(source)
            self.estimate_queue.put(estimated)
            self.log_queue.put(f"处理路径：{source}")
            self.log_queue.put(f"预计任务：{estimated}")
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
