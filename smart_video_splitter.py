import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv")
STRICT_MODE = "strict"
FAST_MODE = "fast"
DEFAULT_MAX_SIZE_VALUE = "4000"
DEFAULT_SIZE_UNIT = "MB"
MACOS_BINARY_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")
MIN_SEGMENT_DURATION = 1.0
TIME_EPSILON = 0.2
STRICT_SEARCH_ROUNDS = 7


def get_executable_path(name):
    """Locate ffmpeg/ffprobe in bundle resources, app folder, or common macOS paths."""
    candidates = []

    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, name))

    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    candidates.append(os.path.join(base_dir, name))

    for directory in MACOS_BINARY_DIRS:
        candidates.append(os.path.join(directory, name))

    path_value = shutil.which(name)
    if path_value:
        candidates.append(path_value)

    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def format_bytes(num_bytes):
    """Format bytes using decimal units, matching upload-platform expectations."""
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(num_bytes)
    for unit in units:
        if value < 1000 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1000.0
    return f"{num_bytes} B"


class SmartVideoSplitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Video Splitter")
        self.root.geometry("900x720")
        self.root.minsize(860, 680)

        self.ffmpeg_path = get_executable_path("ffmpeg")
        self.ffprobe_path = get_executable_path("ffprobe")
        if not self.ffmpeg_path or not self.ffprobe_path:
            messagebox.showerror(
                "依赖缺失",
                (
                    "未找到 ffmpeg / ffprobe。\n\n"
                    "请确保已安装 ffmpeg，或将 ffmpeg/ffprobe 放在脚本同目录。\n"
                    "macOS 可执行：brew install ffmpeg"
                ),
            )
            root.destroy()
            return

        self.target_path = None
        self.max_part_size_bytes = None
        self.is_running = False
        self.abort_event = threading.Event()
        self.ui_queue = queue.Queue()

        self.size_value_var = tk.StringVar(value=DEFAULT_MAX_SIZE_VALUE)
        self.size_unit_var = tk.StringVar(value=DEFAULT_SIZE_UNIT)
        self.mode_var = tk.StringVar(value=STRICT_MODE)
        self.include_subfolders_var = tk.BooleanVar(value=False)
        self.delete_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.check_queue()
        self.validate_size_input(show_message=False)
        self.log("欢迎使用 Smart Video Splitter。")
        self.log("默认模式为“严格不超限”，适合 Telegram 等有明确大小上限的上传场景。")

    def _build_ui(self):
        main_frame = tk.Frame(self.root, padx=16, pady=16)
        main_frame.pack(fill=tk.BOTH, expand=True)

        top_frame = tk.Frame(main_frame)
        top_frame.pack(fill=tk.X)

        self.select_folder_btn = tk.Button(top_frame, text="📂 选择文件夹", command=self.select_folder, width=16)
        self.select_folder_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.select_file_btn = tk.Button(top_frame, text="📄 选择文件", command=self.select_file, width=16)
        self.select_file_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.path_label = tk.Label(top_frame, text="尚未选择文件夹或文件...", fg="grey", anchor="w")
        self.path_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        settings_frame = tk.LabelFrame(main_frame, text="分割规则", padx=12, pady=12)
        settings_frame.pack(fill=tk.X, pady=(14, 10))

        size_row = tk.Frame(settings_frame)
        size_row.pack(fill=tk.X, pady=(0, 6))
        tk.Label(size_row, text="最大体积:", width=10, anchor="w").pack(side=tk.LEFT)

        self.preset_2000_btn = tk.Button(
            size_row, text="2000 MB", width=10, command=lambda: self.apply_size_preset("2000", "MB")
        )
        self.preset_2000_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.preset_4000_btn = tk.Button(
            size_row, text="4000 MB", width=10, command=lambda: self.apply_size_preset("4000", "MB")
        )
        self.preset_4000_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.size_entry = tk.Entry(size_row, textvariable=self.size_value_var, width=14)
        self.size_entry.pack(side=tk.LEFT)
        self.size_entry.bind("<KeyRelease>", self.on_size_input_changed)

        self.unit_combo = ttk.Combobox(
            size_row, textvariable=self.size_unit_var, values=("MB", "GB"), width=6, state="readonly"
        )
        self.unit_combo.pack(side=tk.LEFT, padx=(8, 10))
        self.unit_combo.bind("<<ComboboxSelected>>", self.on_size_input_changed)

        tk.Label(size_row, text="支持精确输入，如 1999.5").pack(side=tk.LEFT)

        self.validation_label = tk.Label(settings_frame, text="", fg="#b42318", anchor="w")
        self.validation_label.pack(fill=tk.X, pady=(0, 8))

        mode_row = tk.Frame(settings_frame)
        mode_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(mode_row, text="分割模式:", width=10, anchor="w").pack(side=tk.LEFT)

        self.strict_mode_radio = tk.Radiobutton(
            mode_row,
            text="严格不超限（默认）",
            variable=self.mode_var,
            value=STRICT_MODE,
            command=self.refresh_run_button_state,
        )
        self.strict_mode_radio.pack(side=tk.LEFT, padx=(0, 12))

        self.fast_mode_radio = tk.Radiobutton(
            mode_row,
            text="极速无损（非严格保证）",
            variable=self.mode_var,
            value=FAST_MODE,
            command=self.refresh_run_button_state,
        )
        self.fast_mode_radio.pack(side=tk.LEFT)

        options_row = tk.Frame(settings_frame)
        options_row.pack(fill=tk.X)
        self.recursive_check = tk.Checkbutton(
            options_row,
            text="批量处理时包含子文件夹",
            variable=self.include_subfolders_var,
        )
        self.recursive_check.pack(side=tk.LEFT, padx=(0, 18))

        self.delete_check = tk.Checkbutton(
            options_row,
            text="所有分片验收成功后删除原始文件（谨慎）",
            variable=self.delete_var,
        )
        self.delete_check.pack(side=tk.LEFT)

        action_frame = tk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=(4, 10))

        self.run_btn = tk.Button(action_frame, text="🚀 开始分割", command=self.run_split, state=tk.DISABLED, width=16)
        self.run_btn.pack(side=tk.LEFT)

        self.abort_btn = tk.Button(action_frame, text="🛑 中止任务", command=self.abort_task, state=tk.DISABLED, width=16)
        self.abort_btn.pack(side=tk.LEFT, padx=(10, 0))

        self.progress_label = tk.Label(main_frame, text="当前文件当前分片进度:", anchor="w")
        self.progress_label.pack(fill=tk.X, pady=(6, 2))

        self.progress_bar = ttk.Progressbar(main_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill=tk.X)

        self.log_area = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, height=24)
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

    def log(self, msg):
        thread_name = threading.current_thread().name
        self.ui_queue.put(("log", f"[{thread_name}] {msg}"))

    def show_error(self, title, content):
        self.ui_queue.put(("error", title, content))

    def push_progress(self, percentage):
        value = max(0, min(100, int(percentage)))
        self.ui_queue.put(("progress", value))

    def check_queue(self):
        try:
            while True:
                event = self.ui_queue.get_nowait()
                event_type = event[0]

                if event_type == "log":
                    self.log_area.insert(tk.END, f"{event[1]}\n")
                    self.log_area.see(tk.END)
                elif event_type == "error":
                    messagebox.showerror(event[1], event[2])
                elif event_type == "progress":
                    self.progress_bar["value"] = event[1]
                elif event_type == "state":
                    self.apply_ui_state(event[1])
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.check_queue)

    def apply_ui_state(self, is_running):
        self.is_running = is_running
        run_state = tk.DISABLED if is_running else tk.NORMAL
        input_state = tk.DISABLED if is_running else tk.NORMAL
        combo_state = tk.DISABLED if is_running else "readonly"

        self.select_folder_btn.config(state=run_state)
        self.select_file_btn.config(state=run_state)
        self.preset_2000_btn.config(state=input_state)
        self.preset_4000_btn.config(state=input_state)
        self.size_entry.config(state=input_state)
        self.unit_combo.config(state=combo_state)
        self.strict_mode_radio.config(state=input_state)
        self.fast_mode_radio.config(state=input_state)
        self.recursive_check.config(state=input_state)
        self.delete_check.config(state=input_state)
        self.abort_btn.config(state=tk.NORMAL if is_running else tk.DISABLED)

        if is_running:
            self.run_btn.config(state=tk.DISABLED)
        else:
            self.refresh_run_button_state()

    def refresh_run_button_state(self):
        is_valid = self.validate_size_input(show_message=False)
        can_run = bool(self.target_path) and is_valid and not self.is_running
        self.run_btn.config(state=tk.NORMAL if can_run else tk.DISABLED)

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.target_path = folder
            self.path_label.config(text=folder, fg="black")
            self.log(f"📁 已选择文件夹: {folder}")
            if self.include_subfolders_var.get():
                self.log("📚 当前开启“包含子文件夹”。")
            self.refresh_run_button_state()

    def select_file(self):
        filetypes = (("视频文件", "*.mp4 *.mov *.mkv"), ("所有文件", "*.*"))
        filepath = filedialog.askopenfilename(filetypes=filetypes)
        if filepath:
            self.target_path = filepath
            self.path_label.config(text=filepath, fg="black")
            self.log(f"📄 已选择文件: {filepath}")
            self.refresh_run_button_state()

    def apply_size_preset(self, value, unit):
        self.size_value_var.set(value)
        self.size_unit_var.set(unit)
        self.validate_size_input(show_message=False)
        self.refresh_run_button_state()

    def on_size_input_changed(self, _event=None):
        self.validate_size_input(show_message=False)
        self.refresh_run_button_state()

    def parse_size_limit(self):
        raw_value = self.size_value_var.get().strip()
        if not raw_value:
            raise ValueError("请输入最大体积。")

        try:
            numeric_value = float(raw_value)
        except ValueError as exc:
            raise ValueError("最大体积必须是数字，例如 2000 或 1999.5。") from exc

        if numeric_value <= 0:
            raise ValueError("最大体积必须大于 0。")

        unit = self.size_unit_var.get().strip().upper()
        if unit not in {"MB", "GB"}:
            raise ValueError("单位仅支持 MB 或 GB。")

        multiplier = 1_000_000 if unit == "MB" else 1_000_000_000
        size_bytes = int(numeric_value * multiplier)
        if size_bytes <= 0:
            raise ValueError("换算后的最大体积无效，请重新输入。")

        return numeric_value, unit, size_bytes

    def validate_size_input(self, show_message=False):
        try:
            numeric_value, unit, size_bytes = self.parse_size_limit()
            self.validation_label.config(text=f"当前上限: {numeric_value:g} {unit} = {size_bytes} 字节")
            self.size_entry.config(bg="white")
            self.max_part_size_bytes = size_bytes
            return True
        except ValueError as exc:
            self.validation_label.config(text=str(exc))
            self.size_entry.config(bg="#ffe8e8")
            self.max_part_size_bytes = None
            if show_message:
                messagebox.showerror("参数错误", str(exc))
            return False

    def run_split(self):
        if not self.target_path:
            messagebox.showerror("错误", "请先选择一个文件夹或文件。")
            return
        if not self.validate_size_input(show_message=True):
            self.refresh_run_button_state()
            return

        self.abort_event.clear()
        self.progress_bar["value"] = 0
        self.apply_ui_state(True)

        worker = threading.Thread(target=self.process_selection, name="Worker", daemon=True)
        worker.start()

    def abort_task(self):
        self.log("🛑 已发送中止信号，当前 ffmpeg 分片完成/终止后会停止。")
        self.abort_event.set()
        self.abort_btn.config(state=tk.DISABLED)

    def process_selection(self):
        scanned_count = 0
        skipped_count = 0
        split_count = 0
        warning_count = 0
        parts_created = 0

        try:
            target_label = self.target_path
            include_subfolders = self.include_subfolders_var.get()
            mode = self.mode_var.get()
            numeric_value, unit, size_limit = self.parse_size_limit()
            self.max_part_size_bytes = size_limit

            mode_text = "严格不超限" if mode == STRICT_MODE else "极速无损（非严格保证）"
            self.log("========================================")
            self.log(f"📍 处理目标: {target_label}")
            self.log(f"📏 分片大小上限: {numeric_value:g} {unit} = {size_limit} 字节 ({format_bytes(size_limit)})")
            self.log(f"⚙️ 分割模式: {mode_text}")
            if os.path.isdir(target_label):
                self.log(f"📚 子文件夹扫描: {'开启' if include_subfolders else '关闭'}")
            self.log("========================================")

            video_files_to_process = self.collect_video_files(target_label, include_subfolders)
            scanned_count = len(video_files_to_process)

            if not video_files_to_process:
                self.log("🤷 未找到可处理的视频文件。当前仅支持 .mp4 / .mov / .mkv。")
                return

            for file_index, filepath in enumerate(video_files_to_process, start=1):
                if self.abort_event.is_set():
                    self.log("🛑 任务已中止，停止处理后续文件。")
                    break

                filename = os.path.basename(filepath)
                filesize = os.path.getsize(filepath)
                self.log("----------------------------------------")
                self.log(f"🎞️ [{file_index}/{scanned_count}] {filename}")
                self.log(f"   原始大小: {format_bytes(filesize)}")

                if filesize <= size_limit:
                    self.log("✅ 文件本身已不超过上限，跳过分割。")
                    skipped_count += 1
                    continue

                result = self.split_file(filepath, filesize, file_index, scanned_count, mode)
                parts_created += result["parts_created"]

                if result["status"] == "success":
                    split_count += 1
                elif result["status"] == "warning":
                    split_count += 1
                    warning_count += 1
                elif result["status"] == "aborted":
                    break

        except Exception as exc:
            self.log(f"💥 处理过程中发生异常: {exc}")
            self.show_error("严重错误", f"处理过程中发生错误:\n{exc}")
        finally:
            self.log("========================================")
            self.log("📊 任务总结报告")
            self.log("----------------------------------------")
            self.log(f"总计扫描/处理文件: {scanned_count} 个")
            self.log(f"成功完成分割文件: {split_count} 个")
            self.log(f"含超限告警文件: {warning_count} 个")
            self.log(f"保持不变文件: {skipped_count} 个")
            self.log(f"共生成分片: {parts_created} 个")
            if self.abort_event.is_set():
                self.log("任务状态: 🛑 用户中止")
            else:
                self.log("任务状态: 🎉 全部完成")
            self.log("========================================")
            self.ui_queue.put(("state", False))

    def collect_video_files(self, path, recursive):
        if os.path.isfile(path):
            return [path] if path.lower().endswith(VIDEO_EXTENSIONS) else []

        if not os.path.isdir(path):
            return []

        video_files = []
        if recursive:
            for root_dir, _, files in os.walk(path):
                for filename in sorted(files):
                    full_path = os.path.join(root_dir, filename)
                    if os.path.isfile(full_path) and filename.lower().endswith(VIDEO_EXTENSIONS):
                        video_files.append(full_path)
        else:
            for filename in sorted(os.listdir(path)):
                full_path = os.path.join(path, filename)
                if os.path.isfile(full_path) and filename.lower().endswith(VIDEO_EXTENSIONS):
                    video_files.append(full_path)
        return video_files

    def split_file(self, filepath, filesize, file_index, total_files, mode):
        try:
            total_duration = self.probe_duration(filepath)
        except Exception as exc:
            self.log(f"❌ 无法读取视频时长: {exc}")
            return {"status": "failed", "parts_created": 0}

        if total_duration <= 0:
            self.log("❌ 视频时长无效，跳过该文件。")
            return {"status": "failed", "parts_created": 0}

        basename, extension = os.path.splitext(os.path.basename(filepath))
        if mode == FAST_MODE:
            return self.split_file_fast(
                filepath, basename, extension, filesize, total_duration, file_index, total_files
            )
        return self.split_file_strict(
            filepath, basename, extension, filesize, total_duration, file_index, total_files
        )

    def split_file_fast(self, filepath, basename, extension, filesize, total_duration, file_index, total_files):
        start_time = 0.0
        part_index = 1
        parts_created = 0
        warnings = 0
        remaining_size_estimate = float(filesize)
        average_bytes_per_second = filesize / total_duration

        self.log("⚡ 使用极速无损模式，优先速度与原始编码保留。")

        while start_time < total_duration - TIME_EPSILON:
            if self.abort_event.is_set():
                return {"status": "aborted", "parts_created": parts_created}

            remaining_duration = max(TIME_EPSILON, total_duration - start_time)
            part_num = f"{part_index:03d}"
            temp_path, final_path = self.make_output_paths(filepath, basename, extension, part_num)

            if remaining_size_estimate <= self.max_part_size_bytes:
                requested_duration = remaining_duration
            else:
                bytes_per_second = max(average_bytes_per_second, remaining_size_estimate / remaining_duration)
                requested_duration = (self.max_part_size_bytes / bytes_per_second) * 0.985
                requested_duration = min(requested_duration, remaining_duration)

            requested_duration = self.normalize_duration(requested_duration, remaining_duration)
            self.log(
                f"  > [{file_index}/{total_files}] Part {part_num}: 预计时长 {requested_duration:.2f}s，"
                f"起点 {start_time:.2f}s"
            )

            attempt = self.render_segment(
                filepath=filepath,
                start_time=start_time,
                duration=requested_duration,
                temp_path=temp_path,
                render_mode="copy",
                bitrate_bps=None,
                log_prefix=f"Part {part_num}",
            )
            if not attempt["success"]:
                if attempt["aborted"]:
                    return {"status": "aborted", "parts_created": parts_created}
                self.log(f"❌ 极速模式分割失败，原文件已保留: {os.path.basename(filepath)}")
                return {"status": "failed", "parts_created": parts_created}

            actual_size = attempt["size"]
            actual_duration = attempt["duration"] if attempt["duration"] and attempt["duration"] > 0 else requested_duration
            self.accept_output(temp_path, final_path)
            parts_created += 1

            oversize = actual_size > self.max_part_size_bytes
            if oversize:
                warnings += 1
                self.log(
                    f"  > ⚠️ Part {part_num} 实际大小 {format_bytes(actual_size)}，"
                    f"超过上限 {format_bytes(self.max_part_size_bytes)}。"
                )
            else:
                self.log(f"  > ✅ Part {part_num} 验收通过，实际大小 {format_bytes(actual_size)}。")

            consumed_duration = self.resolve_consumed_duration(actual_duration, requested_duration, remaining_duration)
            start_time = min(total_duration, start_time + consumed_duration)
            remaining_size_estimate = max(0.0, remaining_size_estimate - actual_size)
            part_index += 1

        if warnings == 0 and self.delete_var.get():
            self.delete_original_file(filepath)
        elif warnings > 0:
            self.log("⚠️ 极速模式存在超限分片告警，已保留原始文件。")
        else:
            self.log("💾 原始文件已保留。")

        status = "warning" if warnings else "success"
        return {"status": status, "parts_created": parts_created}

    def split_file_strict(self, filepath, basename, extension, filesize, total_duration, file_index, total_files):
        start_time = 0.0
        part_index = 1
        parts_created = 0
        average_bytes_per_second = filesize / total_duration

        self.log("🧷 使用严格不超限模式，所有分片都必须通过大小验收。")

        while start_time < total_duration - TIME_EPSILON:
            if self.abort_event.is_set():
                return {"status": "aborted", "parts_created": parts_created}

            remaining_duration = max(TIME_EPSILON, total_duration - start_time)
            part_num = f"{part_index:03d}"
            temp_path, final_path = self.make_output_paths(filepath, basename, extension, part_num)

            if remaining_duration <= MIN_SEGMENT_DURATION:
                candidate_duration = remaining_duration
            else:
                candidate_duration = (self.max_part_size_bytes / max(average_bytes_per_second, 1.0)) * 0.97
                candidate_duration = min(candidate_duration, remaining_duration)

            candidate_duration = self.normalize_duration(candidate_duration, remaining_duration)
            self.log(
                f"  > [{file_index}/{total_files}] Part {part_num}: 严格模式候选时长 {candidate_duration:.2f}s，"
                f"起点 {start_time:.2f}s"
            )

            accepted = self.find_strict_segment(
                filepath=filepath,
                start_time=start_time,
                candidate_duration=candidate_duration,
                remaining_duration=remaining_duration,
                temp_path=temp_path,
                part_num=part_num,
            )
            if not accepted["success"]:
                if accepted["aborted"]:
                    return {"status": "aborted", "parts_created": parts_created}
                self.log(f"❌ 严格模式分割失败，原文件已保留: {os.path.basename(filepath)}")
                self.cleanup_file(temp_path)
                return {"status": "failed", "parts_created": parts_created}

            self.accept_output(temp_path, final_path)
            parts_created += 1
            self.log(
                f"  > ✅ Part {part_num} 验收通过，实际大小 {format_bytes(accepted['size'])}，"
                f"时长 {accepted['duration']:.2f}s，方式: {accepted['method_text']}。"
            )

            consumed_duration = self.resolve_consumed_duration(
                accepted["duration"], accepted["requested_duration"], remaining_duration
            )
            start_time = min(total_duration, start_time + consumed_duration)
            part_index += 1

        if self.delete_var.get():
            self.delete_original_file(filepath)
        else:
            self.log("💾 原始文件已保留。")

        return {"status": "success", "parts_created": parts_created}

    def find_strict_segment(self, filepath, start_time, candidate_duration, remaining_duration, temp_path, part_num):
        best_attempt = None
        high = self.normalize_duration(candidate_duration, remaining_duration)
        low = max(MIN_SEGMENT_DURATION, min(remaining_duration, high * 0.2))

        first_attempt = self.render_segment(
            filepath=filepath,
            start_time=start_time,
            duration=high,
            temp_path=temp_path,
            render_mode="copy",
            bitrate_bps=None,
            log_prefix=f"Part {part_num}",
        )
        if not first_attempt["success"]:
            return first_attempt

        if first_attempt["size"] <= self.max_part_size_bytes:
            first_attempt["method_text"] = "流复制"
            return first_attempt

        self.log(
            f"  > Part {part_num} 流复制首轮超限: {format_bytes(first_attempt['size'])}，"
            "开始缩短时长二分搜索。"
        )
        self.cleanup_file(temp_path)

        search_low = low
        search_high = high

        for _ in range(STRICT_SEARCH_ROUNDS):
            if self.abort_event.is_set():
                return {"success": False, "aborted": True}

            if search_high - search_low <= TIME_EPSILON:
                break

            mid = self.normalize_duration((search_low + search_high) / 2.0, remaining_duration)
            attempt = self.render_segment(
                filepath=filepath,
                start_time=start_time,
                duration=mid,
                temp_path=temp_path,
                render_mode="copy",
                bitrate_bps=None,
                log_prefix=f"Part {part_num}",
            )
            if not attempt["success"]:
                return attempt

            if attempt["size"] <= self.max_part_size_bytes:
                best_attempt = attempt
                search_low = mid
            else:
                self.cleanup_file(temp_path)
                search_high = mid

        if best_attempt:
            best_attempt["method_text"] = "流复制（二分缩短）"
            return best_attempt

        self.log(f"  > Part {part_num} 流复制无法稳定压到上限内，切换严格兜底重编码。")
        fallback_duration = self.normalize_duration(min(candidate_duration, remaining_duration), remaining_duration)
        reencode_attempt = self.find_reencoded_segment(
            filepath=filepath,
            start_time=start_time,
            candidate_duration=fallback_duration,
            remaining_duration=remaining_duration,
            temp_path=temp_path,
            part_num=part_num,
        )
        if reencode_attempt["success"]:
            reencode_attempt["method_text"] = "重编码兜底"
        return reencode_attempt

    def find_reencoded_segment(self, filepath, start_time, candidate_duration, remaining_duration, temp_path, part_num):
        search_low = max(MIN_SEGMENT_DURATION, min(remaining_duration, candidate_duration * 0.25))
        search_high = self.normalize_duration(candidate_duration, remaining_duration)
        best_attempt = None

        for _ in range(STRICT_SEARCH_ROUNDS):
            if self.abort_event.is_set():
                return {"success": False, "aborted": True}

            duration = self.normalize_duration(search_high if best_attempt is None else (search_low + search_high) / 2.0, remaining_duration)
            bitrate_bps = self.calculate_reencode_bitrate(duration)
            attempt = self.render_segment(
                filepath=filepath,
                start_time=start_time,
                duration=duration,
                temp_path=temp_path,
                render_mode="reencode",
                bitrate_bps=bitrate_bps,
                log_prefix=f"Part {part_num}",
            )
            if not attempt["success"]:
                return attempt

            if attempt["size"] <= self.max_part_size_bytes:
                best_attempt = attempt
                search_low = duration
                if search_high - search_low <= TIME_EPSILON:
                    break
            else:
                self.cleanup_file(temp_path)
                search_high = max(search_low, duration - TIME_EPSILON)

        if best_attempt:
            return best_attempt
        return {"success": False, "aborted": False}

    def render_segment(self, filepath, start_time, duration, temp_path, render_mode, bitrate_bps, log_prefix):
        self.cleanup_file(temp_path)
        self.push_progress(0)
        extension = os.path.splitext(temp_path)[1].lower()

        if render_mode == "copy":
            ffmpeg_cmd = [
                self.ffmpeg_path,
                "-hide_banner",
                "-nostdin",
                "-ss",
                f"{start_time:.3f}",
                "-i",
                filepath,
                "-t",
                f"{duration:.3f}",
                "-c",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                "-y",
                temp_path,
                "-stats",
            ]
        else:
            ffmpeg_cmd = [
                self.ffmpeg_path,
                "-hide_banner",
                "-nostdin",
                "-ss",
                f"{start_time:.3f}",
                "-i",
                filepath,
                "-t",
                f"{duration:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-pix_fmt",
                "yuv420p",
                "-b:v",
                str(bitrate_bps),
                "-maxrate",
                str(bitrate_bps),
                "-bufsize",
                str(max(bitrate_bps * 2, 500_000)),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
            ]
            if extension in {".mp4", ".mov", ".m4v"}:
                ffmpeg_cmd.extend(["-movflags", "+faststart"])
            ffmpeg_cmd.extend(["-y", temp_path, "-stats"])

        try:
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                universal_newlines=True,
            )
        except Exception as exc:
            self.cleanup_file(temp_path)
            self.log(f"  > ❌ {log_prefix} 无法启动 ffmpeg: {exc}")
            return {"success": False, "aborted": False}

        try:
            for line in process.stderr:
                if self.abort_event.is_set():
                    self.log(f"  > 🛑 正在终止 {log_prefix} 的 ffmpeg 进程...")
                    process.terminate()
                    process.wait()
                    self.cleanup_file(temp_path)
                    return {"success": False, "aborted": True}

                time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})", line)
                if time_match:
                    hours, minutes, seconds, centiseconds = map(int, time_match.groups())
                    current_seconds = hours * 3600 + minutes * 60 + seconds + centiseconds / 100.0
                    percentage = (current_seconds / max(duration, 0.1)) * 100
                    self.push_progress(percentage)

            process.wait()
            self.push_progress(100)
        finally:
            if process.stderr:
                process.stderr.close()

        if process.returncode != 0:
            self.cleanup_file(temp_path)
            self.log(f"  > ❌ {log_prefix} 处理失败，ffmpeg 返回码: {process.returncode}")
            return {"success": False, "aborted": False}

        if not os.path.exists(temp_path):
            self.log(f"  > ❌ {log_prefix} 输出文件不存在。")
            return {"success": False, "aborted": False}

        try:
            output_size = os.path.getsize(temp_path)
            output_duration = self.probe_duration(temp_path)
        except Exception as exc:
            self.cleanup_file(temp_path)
            self.log(f"  > ❌ {log_prefix} 无法读取输出片段信息: {exc}")
            return {"success": False, "aborted": False}

        return {
            "success": True,
            "aborted": False,
            "size": output_size,
            "duration": output_duration,
            "requested_duration": duration,
        }

    def calculate_reencode_bitrate(self, duration):
        target_total_bitrate = int((self.max_part_size_bytes * 8 / max(duration, 1.0)) * 0.90)
        audio_bitrate = 128_000
        return max(300_000, target_total_bitrate - audio_bitrate)

    def probe_duration(self, filepath):
        ffprobe_cmd = [
            self.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filepath,
        ]
        result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())

    def make_output_paths(self, filepath, basename, extension, part_num):
        directory = os.path.dirname(filepath)
        final_path = os.path.join(directory, f"{basename}_part{part_num}{extension}")
        temp_path = os.path.join(directory, f".{basename}_part{part_num}.tmp{extension}")
        return temp_path, final_path

    def accept_output(self, temp_path, final_path):
        if os.path.exists(final_path):
            os.remove(final_path)
        os.replace(temp_path, final_path)

    def cleanup_file(self, path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def delete_original_file(self, filepath):
        try:
            os.remove(filepath)
            self.log(f"🗑️ 原始文件已删除: {os.path.basename(filepath)}")
        except OSError as exc:
            self.log(f"⚠️ 删除原始文件失败: {exc}")

    def normalize_duration(self, proposed_duration, remaining_duration):
        duration = min(max(proposed_duration, MIN_SEGMENT_DURATION), remaining_duration)
        if remaining_duration <= MIN_SEGMENT_DURATION:
            return remaining_duration
        return max(duration, MIN_SEGMENT_DURATION)

    def resolve_consumed_duration(self, actual_duration, requested_duration, remaining_duration):
        candidates = [actual_duration, requested_duration, MIN_SEGMENT_DURATION]
        duration = next((value for value in candidates if value and value > 0), MIN_SEGMENT_DURATION)
        duration = max(duration, MIN_SEGMENT_DURATION if remaining_duration > MIN_SEGMENT_DURATION else remaining_duration)
        return min(duration, remaining_duration)


if __name__ == "__main__":
    root = tk.Tk()
    app = SmartVideoSplitterApp(root)
    root.mainloop()
