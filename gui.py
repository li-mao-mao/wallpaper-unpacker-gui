import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.extractor import CancelledError, count_exportable_items, process_input
from app.local_state import get_app_dir, load_settings, save_settings

PROJECT_LINK_TEXT = "Wallpaper-Unpacker-GUI"
PROJECT_LINK_URL = "https://github.com/li-mao-mao"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Wallpaper-Unpacker-GUI")
        self.root.geometry("1180x780")
        self.root.minsize(820, 560)
        self.root.configure(bg="#eef3fb")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)

        self.settings = load_settings()

        self.input_var = tk.StringVar(value=self.settings.get("last_input", ""))
        self.output_var = tk.StringVar(value=self.settings.get("last_output", ""))
        self.status_var = tk.StringVar(value="就绪")
        self.hint_var = tk.StringVar(value=PROJECT_LINK_TEXT)
        self.summary_total = tk.StringVar(value="0")
        self.summary_success = tk.StringVar(value="0")
        self.summary_skipped = tk.StringVar(value="0")
        self.summary_failed = tk.StringVar(value="0")
        self.progress_text = tk.StringVar(value="等待开始")
        self.estimated_total = tk.StringVar(value="0")
        self.local_path_var = tk.StringVar(value=str(get_app_dir()))
        self.last_run_var = tk.StringVar(value=self.settings.get("last_run_time", "尚未运行"))
        self.auto_open_var = tk.BooleanVar(value=bool(self.settings.get("auto_open_output", False)))
        self.same_folder_var = tk.BooleanVar(value=bool(self.settings.get("same_folder_output", False)))
        self.output_rule_var = tk.StringVar(value="")

        self.running = False
        self.cancel_requested = False
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.done_queue: "queue.Queue[tuple]" = queue.Queue()
        self.progress_queue: "queue.Queue[dict]" = queue.Queue()
        self._content_window = None

        self._configure_style()
        self._build_ui()
        self._update_output_rule_text()
        self._poll_queues()
        self._refresh_estimate_async()

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("App.TFrame", background="#eef3fb")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Inner.TFrame", background="#f8fbff")
        style.configure("Topbar.TFrame", background="#eef3fb")
        style.configure("Title.TLabel", background="#eef3fb", foreground="#0f172a", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Sub.TLabel", background="#eef3fb", foreground="#475569", font=("Microsoft YaHei UI", 10))
        style.configure("Link.TLabel", background="#eef3fb", foreground="#2563eb", font=("Microsoft YaHei UI", 10, "underline"))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#64748b", font=("Microsoft YaHei UI", 9))
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#0f172a", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Body.TLabel", background="#ffffff", foreground="#334155", font=("Microsoft YaHei UI", 10))
        style.configure("BodySoft.TLabel", background="#f8fbff", foreground="#334155", font=("Microsoft YaHei UI", 10))
        style.configure("Big.TLabel", background="#ffffff", foreground="#111827", font=("Segoe UI", 18, "bold"))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(14, 9))
        style.configure("Ghost.TButton", font=("Microsoft YaHei UI", 10), padding=(12, 8))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(10, 7))
        style.configure("TEntry", padding=7)
        style.configure("TCheckbutton", background="#ffffff", font=("Microsoft YaHei UI", 9))
        style.configure("TProgressbar", thickness=12)

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root, style="App.TFrame")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)

        self.viewport = tk.Canvas(shell, bg="#eef3fb", highlightthickness=0)
        self.viewport.grid(row=0, column=0, sticky="nsew")

        v_scroll = ttk.Scrollbar(shell, orient="vertical", command=self.viewport.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll = ttk.Scrollbar(shell, orient="horizontal", command=self.viewport.xview)
        h_scroll.grid(row=1, column=0, sticky="ew")
        self.viewport.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        outer = ttk.Frame(self.viewport, style="App.TFrame", padding=18)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        self._content_window = self.viewport.create_window((0, 0), window=outer, anchor="nw")

        outer.bind("<Configure>", self._on_outer_configure)
        self.viewport.bind("<Configure>", self._on_viewport_configure)
        self.viewport.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.viewport.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel, add="+")

        topbar = ttk.Frame(outer, style="Topbar.TFrame")
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.columnconfigure(0, weight=1)

        ttk.Label(topbar, text="Wallpaper-Unpacker-GUI", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(topbar, text="一个让用户能够轻松从 Wallpaper Engine 壁纸包（.pkg / .tex）中提取原始图片的图形化工具", style="Sub.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 0))
        link_label = ttk.Label(topbar, textvariable=self.hint_var, style="Link.TLabel", cursor="hand2")
        link_label.grid(row=0, column=1, sticky="e")
        link_label.bind("<Button-1>", self.open_project_link)

        form = ttk.Frame(outer, style="Card.TFrame", padding=18)
        form.grid(row=1, column=0, sticky="ew", pady=(16, 12))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="输入路径", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=(12, 8))
        input_actions = ttk.Frame(form, style="Card.TFrame")
        input_actions.grid(row=0, column=2, sticky="e")
        ttk.Button(input_actions, text="选文件", command=self.pick_input_file).pack(side="left")
        ttk.Button(input_actions, text="选文件夹", command=self.pick_input_dir).pack(side="left", padx=(8, 0))

        ttk.Label(form, text="输出目录", style="CardTitle.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(form, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=(12, 8), pady=(12, 0))
        output_actions = ttk.Frame(form, style="Card.TFrame")
        output_actions.grid(row=1, column=2, sticky="e", pady=(12, 0))
        ttk.Button(output_actions, text="选择输出", command=self.pick_output_dir).pack(side="left")
        ttk.Button(output_actions, text="打开输出", command=self.open_output_dir).pack(side="left", padx=(8, 0))

        options = ttk.Frame(form, style="Inner.TFrame", padding=12)
        options.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        options.columnconfigure(0, weight=1)
        options.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            options,
            text="导出结果全部放进同一个文件夹",
            variable=self.same_folder_var,
            command=self._on_same_folder_changed,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            options,
            text="完成后自动打开输出目录",
            variable=self.auto_open_var,
            command=self._persist_settings,
        ).grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(options, textvariable=self.output_rule_var, style="BodySoft.TLabel", justify="left").grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(10, 0),
        )

        toolbar = ttk.Frame(outer, style="Topbar.TFrame")
        toolbar.grid(row=2, column=0, sticky="ew")
        ttk.Button(toolbar, text="开始导出", style="Primary.TButton", command=self.start_extract).pack(side="left")
        ttk.Button(toolbar, text="停止", style="Ghost.TButton", command=self.request_cancel).pack(side="left", padx=(10, 0))
        ttk.Button(toolbar, text="清空日志", style="Ghost.TButton", command=self.clear_log).pack(side="left", padx=(10, 0))
        ttk.Button(toolbar, text="打开本地运行目录", style="Ghost.TButton", command=self.open_app_dir).pack(side="left", padx=(10, 0))
        ttk.Label(toolbar, textvariable=self.status_var, style="Sub.TLabel").pack(side="right")

        progress_card = ttk.Frame(outer, style="Card.TFrame", padding=14)
        progress_card.grid(row=3, column=0, sticky="ew", pady=(10, 10))
        progress_card.columnconfigure(0, weight=1)
        ttk.Label(progress_card, textvariable=self.progress_text, style="Body.TLabel").grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(progress_card, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        content = ttk.Panedwindow(outer, orient="horizontal")
        content.grid(row=4, column=0, sticky="nsew")

        left = ttk.Frame(content, style="Card.TFrame", padding=16)
        right = ttk.Frame(content, style="Card.TFrame", padding=16)
        content.add(left, weight=2)
        content.add(right, weight=5)

        ttk.Label(left, text="运行概览", style="CardTitle.TLabel").pack(anchor="w")
        summary_grid = ttk.Frame(left, style="Card.TFrame")
        summary_grid.pack(fill="x", pady=(12, 0))
        summary_grid.columnconfigure(0, weight=1)
        for idx, (title, variable) in enumerate(
            [
                ("预计任务", self.estimated_total),
                ("成功", self.summary_success),
                ("跳过", self.summary_skipped),
                ("失败", self.summary_failed),
            ]
        ):
            self._stat_card(summary_grid, title, variable).grid(row=idx, column=0, sticky="ew", pady=(0 if idx == 0 else 10, 0))

        local_box = ttk.Frame(left, style="Inner.TFrame", padding=12)
        local_box.pack(fill="x", pady=(16, 0))
        ttk.Label(local_box, text="本地化说明", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            local_box,
            text=(
                "• 本工具完全本地运行，不会上传任何数据。"
            ),
            style="BodySoft.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(8, 0))
        ttk.Label(local_box, textvariable=self.local_path_var, style="BodySoft.TLabel").pack(anchor="w", pady=(10, 0))

        runtime_box = ttk.Frame(left, style="Inner.TFrame", padding=12)
        runtime_box.pack(fill="x", pady=(12, 0))
        ttk.Label(runtime_box, text="最近运行", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(runtime_box, textvariable=self.last_run_var, style="BodySoft.TLabel").pack(anchor="w", pady=(6, 0))

        ttk.Label(right, text="处理日志", style="CardTitle.TLabel").pack(anchor="w")
        log_wrap = ttk.Frame(right, style="Inner.TFrame", padding=1)
        log_wrap.pack(fill="both", expand=True, pady=(12, 0))
        self.log = tk.Text(
            log_wrap,
            wrap="word",
            relief="flat",
            bd=0,
            bg="#0f172a",
            fg="#dbeafe",
            insertbackground="#e2e8f0",
            font=("Consolas", 10),
            padx=14,
            pady=14,
            height=24,
        )
        scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._append_log("欢迎使用。本工具完全离线运行，日志与配置仅存本机。")

        self.input_var.trace_add("write", lambda *_: self._on_path_changed())
        self.output_var.trace_add("write", lambda *_: self._persist_settings())

    def _on_outer_configure(self, _event=None) -> None:
        self.viewport.configure(scrollregion=self.viewport.bbox("all"))

    def _on_viewport_configure(self, event: tk.Event) -> None:
        if self._content_window is not None:
            self.viewport.itemconfigure(self._content_window, width=max(event.width, 980))
        self.viewport.configure(scrollregion=self.viewport.bbox("all"))

    def _on_mousewheel(self, event: tk.Event) -> None:
        if event.state & 0x0001:
            return
        delta = -1 * int(event.delta / 120) if event.delta else 0
        if delta:
            self.viewport.yview_scroll(delta, "units")

    def _on_shift_mousewheel(self, event: tk.Event) -> None:
        delta = -1 * int(event.delta / 120) if event.delta else 0
        if delta:
            self.viewport.xview_scroll(delta, "units")

    def _stat_card(self, parent: ttk.Frame, title: str, value_var: tk.StringVar) -> ttk.Frame:
        card = ttk.Frame(parent, style="Inner.TFrame", padding=12)
        ttk.Label(card, text=title, style="BodySoft.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=value_var, style="Big.TLabel").pack(anchor="w", pady=(4, 0))
        return card

    def _on_path_changed(self) -> None:
        self._persist_settings()
        self._refresh_estimate_async()

    def _on_same_folder_changed(self) -> None:
        self._update_output_rule_text()
        self._persist_settings()

    def _update_output_rule_text(self) -> None:
        if self.same_folder_var.get():
            self.output_rule_var.set("当前规则：所有导出图片都会直接进入你选择的输出目录，不额外套文件夹。")
        else:
            self.output_rule_var.set("当前规则：TEX直接输出到目标目录，PKG只保留一层包名文件夹。")

    def _persist_settings(self) -> None:
        payload = {
            "last_input": self.input_var.get().strip(),
            "last_output": self.output_var.get().strip(),
            "same_folder_output": self.same_folder_var.get(),
            "auto_open_output": self.auto_open_var.get(),
            "last_run_time": self.last_run_var.get(),
        }
        save_settings(payload)

    def _refresh_estimate_async(self) -> None:
        input_path = self.input_var.get().strip()
        if not input_path:
            self.estimated_total.set("0")
            return

        def worker() -> None:
            try:
                p = Path(input_path).expanduser()
                total = count_exportable_items(p) if p.exists() else 0
                self.root.after(0, lambda: self.estimated_total.set(str(total)))
            except Exception:
                self.root.after(0, lambda: self.estimated_total.set("?"))

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

        try:
            done = self.done_queue.get_nowait()
        except queue.Empty:
            done = None

        if done is not None:
            kind, payload = done
            if kind == "done":
                stats = payload
                self.summary_total.set(str(stats.total))
                self.summary_success.set(str(stats.success))
                self.summary_skipped.set(str(stats.skipped))
                self.summary_failed.set(str(stats.failed))
                self.status_var.set("处理完成")
                self.progress_text.set(f"完成：{stats.processed}/{stats.total} 项")
                self.progress["value"] = 100 if stats.total else 0
                self.last_run_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                self._persist_settings()
                if self.auto_open_var.get():
                    self.open_output_dir()
            elif kind == "cancelled":
                self.status_var.set("已取消")
                self.progress_text.set("任务已停止")
                self._append_log(str(payload))
            else:
                self.status_var.set("处理失败")
                self._append_log(f"失败：{payload}")
                messagebox.showerror("处理失败", str(payload))
            self._finish_extract()

        self.root.after(80, self._poll_queues)

    def _apply_progress(self, payload: dict) -> None:
        total = int(payload.get("total", 0) or 0)
        processed = int(payload.get("processed", 0) or 0)
        detail = str(payload.get("detail", ""))
        event = payload.get("event")
        shown_total = total or int(self.estimated_total.get() or 0)
        if shown_total > 0:
            self.progress["value"] = min(100, processed / shown_total * 100)
        if event == "item_start" and detail:
            self.progress_text.set(f"处理中：{processed}/{shown_total or '?'} · {detail}")
        elif event == "item_done":
            self.progress_text.set(f"已完成：{processed}/{shown_total or '?'}")

    def _append_log(self, text: str) -> None:
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def clear_log(self) -> None:
        if self.running:
            return
        self.log.delete("1.0", tk.END)
        self._append_log("日志已清空。")
        self.status_var.set("就绪")
        self.progress_text.set("等待开始")
        self.progress["value"] = 0
        self.summary_total.set("0")
        self.summary_success.set("0")
        self.summary_skipped.set("0")
        self.summary_failed.set("0")

    def pick_input_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Package/Tex 文件", "*.pkg *.tex"), ("所有文件", "*.*")])
        if path:
            self.input_var.set(path)

    def pick_input_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.input_var.set(path)

    def pick_output_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.output_var.set(path)

    def open_app_dir(self) -> None:
        self._open_path(get_app_dir())

    def open_output_dir(self) -> None:
        path = self.output_var.get().strip()
        if not path:
            return
        p = Path(path)
        if not p.exists():
            messagebox.showinfo("提示", "输出目录还不存在，请先运行一次导出。")
            return
        self._open_path(p)

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def open_project_link(self, _event=None) -> None:
        try:
            webbrowser.open(PROJECT_LINK_URL, new=2)
        except Exception as e:
            messagebox.showerror("打开链接失败", str(e))

    def request_cancel(self) -> None:
        if not self.running:
            return
        self.cancel_requested = True
        self.status_var.set("正在停止…")
        self._append_log("收到停止请求，正在等待当前文件处理结束…")

    def start_extract(self) -> None:
        if self.running:
            return

        input_path = self.input_var.get().strip()
        output_dir = self.output_var.get().strip()

        if not input_path or not output_dir:
            messagebox.showerror("错误", "请先选择输入路径和输出目录")
            return

        source = Path(input_path).expanduser()
        out_dir = Path(output_dir).expanduser()
        if not source.exists():
            messagebox.showerror("错误", "输入路径不存在")
            return

        self.clear_log()
        self.cancel_requested = False
        self.running = True
        self.status_var.set("处理中…")
        self.progress_text.set("正在准备任务…")
        self.progress["value"] = 0
        self._persist_settings()

        thread = threading.Thread(
            target=self._worker,
            args=(str(source), str(out_dir), self.same_folder_var.get()),
            daemon=True,
        )
        thread.start()

    def _worker(self, input_path: str, output_dir: str, same_folder: bool) -> None:
        try:
            source = Path(input_path)
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            estimated = count_exportable_items(source)
            self.root.after(0, lambda: self.estimated_total.set(str(estimated)))
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
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    launch()
