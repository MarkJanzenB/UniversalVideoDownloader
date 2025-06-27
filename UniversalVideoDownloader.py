import tkinter as tk
from tkinter import scrolledtext, messagebox, END, ttk, filedialog
import subprocess
import sys
import os
import threading
import queue
import shutil
import time
import re
import json
import tkinter.font

# --- Constants for consistent naming and values ---
# These are now mostly internal or default values, can be overridden by settings
DEFAULT_DOWNLOADS_DIR = "downloads"
TEMP_SUBDIR = "temp"
DEFAULT_SOURCE = "Default"  # Renamed from YOUTUBE_SOURCE
XTREAM_SOURCE = "XtremeStream"
LOCAL_SOURCE = "Local"
DEFAULT_MAX_CONCURRENT_DOWNLOADS = 2  # Default, overridden by settings
HISTORY_FILE = "download_history.json"  # History file is always fixed
CONFIG_FILE = "config.json"  # Configuration file name

# Colors for buttons/status
COLOR_ADD_BUTTON = "#28A745"  # Green
COLOR_ABORT_BUTTON = "#DC3545"  # Red
COLOR_CLEAR_BUTTON = "#FFC107"  # Yellow-Orange
COLOR_OPEN_FOLDER_BUTTON = "#6C754C"  # Dark Grey/Greenish Grey
COLOR_OPEN_FILE_BUTTON = "#17A2B8"  # Info Blue/Cyan
COLOR_BROWSE_FILE_BUTTON = "#007BFF"  # Blue for browse
COLOR_REMOVE_BUTTON = "#6C757D"  # Grey

COLOR_STATUS_READY = "black"
COLOR_STATUS_PROGRESS = "#007BFF"  # Blue
COLOR_STATUS_COMPLETE = "#28A745"  # Green
COLOR_STATUS_FAILED = "#DC3545"  # Red
COLOR_STATUS_ABORTED = "#FFC107"  # Orange

# Font for better aesthetics
MAIN_FONT = ("Inter", 10)
BOLD_FONT = ("Inter", 12, "bold")
SMALL_FONT = ("Inter", 9)
MONO_FONT = ("Roboto Mono", 9)


class DownloadItem:
    """
    Manages the UI and logic for a single download/conversion.
    Can represent an active/queued item or a finished history item.
    """

    def __init__(self, app_instance, item_data, is_active_item=True):
        self.parent_frame = None
        self.app_instance = app_instance

        self.item_id = item_data.get('id')
        self.source_path = item_data.get('source_path', item_data.get('url'))
        self.quality = item_data.get('quality', 'N/A')
        self.filename = str(item_data.get('filename', ''))
        self.mp3_conversion = item_data.get('mp3_conversion', False)
        self.source = item_data.get('source', 'N/A')
        self.referer = item_data.get('referer', '')
        self.video_title = item_data.get('video_title', 'Fetching Title...')
        self.status = item_data.get('status', 'queued')
        self.date_added = item_data.get('date_added', 'N/A')
        self.date_completed = item_data.get('date_completed', 'N/A')
        self.filename_provided_by_user = item_data.get('filename_provided_by_user', False)
        self.elapsed_time_seconds = item_data.get('elapsed_time_seconds', 0)

        self.is_local_conversion = (self.source == LOCAL_SOURCE)

        if self.is_local_conversion:
            self.video_title = os.path.basename(self.source_path)
            self.filename = os.path.splitext(os.path.basename(self.source_path))[0]
            self.is_title_fetched = True
            self.ready_for_download = True
            self.expected_final_ext = ".mp4"
        else:
            self.is_title_fetched = self.filename_provided_by_user or (self.video_title != 'Fetching Title...')
            self.ready_for_download = not (
                    is_active_item and not self.filename_provided_by_user and not self.is_title_fetched)
            self.expected_final_ext = ".mp3" if self.mp3_conversion else ".mp4"

        self.process = None
        self.output_queue = queue.Queue()
        self.start_time = None
        self.last_update_time = None
        self.is_aborted = False
        self.is_merging = False
        self.is_active_item = is_active_item

        self.frame = None
        self.retry_button = None

        if self.is_active_item and not self.filename_provided_by_user and not self.is_title_fetched and not self.is_local_conversion:
            self.fetch_title_async()

    def _build_frame_widgets(self):
        """Builds or rebuilds the UI elements for this individual download item."""
        if self.frame and self.frame.winfo_exists():
            self.frame.destroy()

        self.frame = tk.Frame(self.parent_frame, bd=2, relief=tk.GROOVE, padx=2, pady=2, bg="#f0f0f0")
        self.frame.columnconfigure(0, weight=4)
        self.frame.columnconfigure(1, weight=2)
        self.frame.columnconfigure(2, weight=1)
        self.frame.columnconfigure(3, weight=1)
        self.frame.columnconfigure(4, weight=1)
        self.frame.columnconfigure(5, weight=1)
        self.frame.columnconfigure(6, weight=1)  # Added for new 'Remove' button

        self.title_label = tk.Label(self.frame, text="", font=MAIN_FONT, anchor="w", bg="#f0f0f0", justify="left")
        self.title_label.grid(row=0, column=0, sticky="nw", padx=2, pady=0)

        self.status_progress_frame = tk.Frame(self.frame, bg="#f0f0f0")
        self.status_progress_frame.grid(row=0, column=1, sticky="nsew", padx=2, pady=0)
        self.status_progress_frame.columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(self.status_progress_frame, orient="horizontal", mode="determinate",
                                            length=120)
        self.status_label = tk.Label(self.status_progress_frame, text="", font=SMALL_FONT, anchor="center",
                                     fg=self._get_status_color(self.status), bg="#f0f0f0", width=14)

        if self.is_active_item:
            self.progress_bar.grid(row=0, column=0, sticky="ew")
            self.status_label.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.progress_bar.grid_forget()
            self.status_label.grid(row=0, column=0, sticky="ew")

        self.date_added_label = tk.Label(self.frame, text=self.date_added, font=SMALL_FONT, anchor="w", bg="#f0f0f0",
                                         width=10)
        self.date_added_label.grid(row=0, column=2, sticky="w", padx=2, pady=0)

        self.date_completed_label = tk.Label(self.frame, text=self.date_completed, font=SMALL_FONT, anchor="w",
                                             bg="#f0f0f0", width=10)
        self.date_completed_label.grid(row=0, column=3, sticky="w", padx=2, pady=0)

        self.elapsed_time_label = tk.Label(self.frame, text="", font=SMALL_FONT, anchor="w", bg="#f0f0f0", width=8)
        self.elapsed_time_label.grid(row=0, column=4, sticky="w", padx=2, pady=0)

        self.abort_button = tk.Button(self.frame, text="Abort", command=self.abort_download, bg=COLOR_ABORT_BUTTON,
                                      fg="white", font=SMALL_FONT, width=8)
        self.open_file_button = tk.Button(self.frame, text="Open File", command=self._open_file_location,
                                          bg=COLOR_OPEN_FILE_BUTTON, fg="white", font=SMALL_FONT, width=10)
        self.retry_button = tk.Button(self.frame, text="Retry", command=self.retry_download, bg=COLOR_ADD_BUTTON,
                                      fg="white", font=SMALL_FONT, width=10)
        self.remove_button = tk.Button(self.frame, text="Remove", command=self._confirm_and_remove,
                                       bg=COLOR_REMOVE_BUTTON,
                                       fg="white", font=SMALL_FONT, width=10)  # New Remove button

        if self.is_active_item:
            self.abort_button.grid(row=0, column=5, sticky="e", padx=2, pady=0)
            self.remove_button.grid(row=0, column=6, sticky="e", padx=2, pady=0)  # Placed next to abort
        else:
            if self.status in ['failed', 'aborted', 'cancelled']:
                self.retry_button.grid(row=0, column=5, sticky="e", padx=2, pady=0)
                self.remove_button.grid(row=0, column=6, sticky="e", padx=2, pady=0)  # Placed next to retry
            elif self.status == 'completed':
                self.open_file_button.grid(row=0, column=5, sticky="e", padx=2, pady=0)
                self.remove_button.grid(row=0, column=6, sticky="e", padx=2, pady=0)  # Placed next to open file

        self._update_progress_visibility()

    def _update_progress_visibility(self):
        """Manages the visibility of the progress bar and status label based on item state."""
        if self.is_active_item:
            if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
                self.progress_bar.lift()
            if hasattr(self, 'status_label') and self.status_label.winfo_exists():
                self.status_label.place(relx=0.5, rely=0.5, anchor="center")
                self.status_label.config(bg="#f0f0f0")
        else:
            if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
                self.progress_bar.grid_forget()
            if hasattr(self, 'status_label') and self.status_label.winfo_exists():
                self.status_label.place_forget()
                self.status_label.grid(row=0, column=0, sticky="ew")
                self.status_label.config(bg="#f0f0f0")

    def _get_status_color(self, status_text):
        """Returns the color based on status text."""
        if status_text == "queued" or "Starting" in status_text:
            return COLOR_STATUS_READY
        elif "Downloading" in status_text or "Converting" in status_text or status_text == "active":
            return COLOR_STATUS_PROGRESS
        elif status_text == "completed":
            return COLOR_STATUS_COMPLETE
        elif status_text == "failed":
            return COLOR_STATUS_FAILED
        elif status_text == "aborted" or status_text == "cancelled":
            return COLOR_STATUS_ABORTED
        return "black"

    def _format_seconds_to_dd_hh_mm_ss(self, total_seconds):
        """Formats total seconds into HH:MM:SS."""
        if total_seconds < 0:
            total_seconds = 0
        hours = int(total_seconds // 3600)
        remaining_seconds = total_seconds % 3600
        minutes = int(remaining_seconds // 60)
        seconds = int(remaining_seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def fetch_title_async(self):
        """Fetches the video title asynchronously and updates the label. Only for Default/XtremeStream."""
        if self.is_local_conversion:
            self.is_title_fetched = True
            self.ready_for_download = True
            self.app_instance.master.after(0, self.app_instance._refresh_display_order)
            return

        def _fetch():
            try:
                command = [self.app_instance.yt_dlp_path, "--print-json", "--skip-download", self.source_path]
                if self.source == XTREAM_SOURCE and self.referer:
                    command += ["--add-header", f"referer: {self.referer}"]

                result = subprocess.run(command, capture_output=True, text=True, check=True,
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                                        timeout=30)
                metadata = json.loads(result.stdout)
                self.video_title = metadata.get('title', 'Unknown Title')

                if not self.filename_provided_by_user:
                    sanitized_title = re.sub(r'[\\/:*?"<>|]', '', self.video_title)
                    self.filename = sanitized_title if sanitized_title else f"VideoPlayback_{self.item_id}"

                self.is_title_fetched = True
                self.ready_for_download = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)

            except FileNotFoundError:
                self.video_title = "Error: yt-dlp.exe not found."
                if not self.filename_provided_by_user: self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"FileNotFoundError: yt-dlp.exe not found or not in PATH for URL: {self.source_path}")
            except subprocess.CalledProcessError as e:
                self.video_title = f"Error fetching title: Command failed. {e.stderr.strip()}"
                if not self.filename_provided_by_user: self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"subprocess.CalledProcessError for URL {self.source_path}: {e.stderr.strip()}")
            except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
                self.video_title = f"Error fetching title: {e}"
                if not self.filename_provided_by_user: self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"Decoding/Timeout Error for URL {self.source_path}: {e}")
            except Exception as e:
                self.video_title = f"Unexpected error fetching title: {e}"
                if not self.filename_provided_by_user: self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"General Error fetching title for URL {self.source_path}: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_title_label(self):
        """Updates the title label on the UI with fetched info, and sets wraplength dynamically."""
        self.frame.update_idletasks()
        total_frame_width = self.app_instance.downloads_canvas.winfo_width() if self.app_instance.downloads_canvas.winfo_width() > 0 else 900
        name_column_pixel_width = int(total_frame_width * 4 / 10) - 30
        name_column_pixel_width = max(10, name_column_pixel_width)
        self.title_label.config(wraplength=name_column_pixel_width)

        display_name_raw = ""
        if "Error" in self.video_title or self.status in ['failed', 'aborted', 'cancelled']:
            display_name_raw = f"{self.status.capitalize()}: {self.video_title}"
        elif self.is_local_conversion:
            display_name_raw = self.video_title
        else:
            display_name_raw = self.video_title if self.video_title and self.video_title != 'Fetching Title...' else (
                os.path.basename(self.filename) if self.filename else f"VideoPlayback_{self.item_id}")

        display_name_full = f"{display_name_raw} ({self.source})"
        font_obj = tkinter.font.Font(family=MAIN_FONT[0], size=MAIN_FONT[1])
        text_width_px = font_obj.measure(display_name_full)

        display_name_final = display_name_full
        if text_width_px > name_column_pixel_width:
            truncated_text = ""
            for i in range(len(display_name_full)):
                test_text = display_name_full[:i + 1] + "..."
                if font_obj.measure(test_text) > name_column_pixel_width:
                    truncated_text = display_name_full[:i] + "..."
                    break
            if truncated_text:
                display_name_final = truncated_text

        if self.title_label.winfo_exists():
            self.title_label.config(text=display_name_final)
        if self.date_added_label.winfo_exists():
            self.date_added_label.config(text=self.date_added)
        if self.date_completed_label.winfo_exists():
            self.date_completed_label.config(text=self.date_completed)
        if self.elapsed_time_label.winfo_exists():
            self.elapsed_time_label.config(text=self._format_seconds_to_dd_hh_mm_ss(self.elapsed_time_seconds))

    def start_download(self):
        """Starts the yt-dlp or ffmpeg process for this item in a new thread."""
        self.is_aborted = False
        self.is_merging = False
        self.start_time = time.time()
        self.last_update_time = time.time()
        self.update_status("active", COLOR_STATUS_PROGRESS)
        self.is_active_item = True
        self.app_instance._refresh_display_order()

        if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
            self.progress_bar.config(value=0, mode="determinate")
        if hasattr(self, 'status_label') and self.status_label.winfo_exists():
            self.status_label.config(bg="#f0f0f0")

        if self.abort_button.winfo_exists():
            self.abort_button.config(state="normal")
        if self.elapsed_time_label.winfo_exists():
            self.elapsed_time_label.config(text=self._format_seconds_to_dd_hh_mm_ss(0))

        command = self._build_command()
        is_ffmpeg_process = (self.source == LOCAL_SOURCE)
        threading.Thread(target=self._run_conversion_process, args=(command, is_ffmpeg_process,), daemon=True).start()

    def _build_command(self):
        """Builds the yt-dlp or ffmpeg command for this specific item."""
        downloads_dir = os.path.join(os.getcwd(), self.app_instance.settings['output_directory'])  # Use settings
        temp_dir = os.path.join(downloads_dir, TEMP_SUBDIR, str(self.item_id))
        os.makedirs(temp_dir, exist_ok=True)
        out_name = self.filename

        if self.is_local_conversion:
            command = ["ffmpeg", "-i", self.source_path]
            if self.quality == "Same as source":
                command += ["-c:v", "copy", "-c:a", "copy", "-map", "0", "-y",
                            os.path.join(temp_dir, out_name + ".mp4")]
            else:
                crf_value = 23
                if self.quality == "High Quality MP4":
                    crf_value = 18
                elif self.quality == "Low Quality MP4":
                    crf_value = 28
                command += ["-preset", "medium", "-crf", str(crf_value), "-c:v", "libx264", "-c:a", "aac", "-b:a",
                            "128k", "-y", os.path.join(temp_dir, out_name + ".mp4")]
            self.expected_final_ext = ".mp4"
            print(f"FFmpeg Command: {' '.join(command)}")
        else:
            command = [self.app_instance.yt_dlp_path, self.source_path]
            if self.source == XTREAM_SOURCE and self.referer:
                command += ["--add-header", f"referer: {self.referer}"]
            if self.mp3_conversion:
                command += ["--extract-audio", "--audio-format", "mp3", "--output",
                            os.path.join(temp_dir, out_name + ".mp3")]
                self.expected_final_ext = ".mp3"
            else:
                command += ["--recode-video", "mp4", "--output", os.path.join(temp_dir, out_name + ".mp4")]
                self.expected_final_ext = ".mp4"
            if self.source == DEFAULT_SOURCE:  # Changed from YOUTUBE_SOURCE
                if "Auto (Best available)" in self.quality:
                    command += ['-f', 'bestvideo+bestaudio/best']
                elif self.quality == "High Quality - 1080p":
                    command += ['-f', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]']
                elif self.quality == "Medium Quality - 720p":
                    command += ['-f', 'bestvideo[height<=720]+bestaudio/best[height<={res}]']
                elif "Combined" in self.quality:
                    res = re.search(r'(\d+)p', self.quality).group(1)
                    command += ['-f', f'bestvideo[height<={res}]+bestaudio/best[height<={res}]']
                elif "Video Only" in self.quality:
                    res = re.search(r'(\d+)p', self.quality).group(1)
                    command += ['-f', f'bestvideo[height<={res}]']

            command += ["--paths", f"temp:{temp_dir}", "--newline"]
            print(f"Yt-dlp Command: {' '.join(command)}")
        return command

    def _run_conversion_process(self, command, is_ffmpeg_process):
        """Runs the subprocess (yt-dlp or ffmpeg) and captures its output."""
        rc = -1
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                            bufsize=1, universal_newlines=True, creationflags=creationflags)
            for line in self.process.stdout:
                if self.is_aborted: break
                self.output_queue.put(line)
                if self.app_instance.log_window_visible and self.app_instance.log_text:
                    self.app_instance.master.after(0, lambda l=line: self._append_to_log(l))
                if is_ffmpeg_process:
                    self._parse_ffmpeg_output_for_progress(line)
                else:
                    self._parse_output_for_progress(line)
                if self.start_time:
                    elapsed = time.time() - self.start_time
                    if self.elapsed_time_label.winfo_exists() and self.elapsed_time_label.winfo_ismapped():
                        self.app_instance.master.after(0, lambda e=elapsed: self.elapsed_time_label.config(
                            text=self._format_seconds_to_dd_hh_mm_ss(e)))
            rc = self.process.wait()
            if self.is_merging:
                if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists(): self.progress_bar.stop()

            if self.is_aborted:
                final_status = "aborted";
                self.update_status("aborted", COLOR_STATUS_ABORTED)
            elif rc == 0:
                final_status = "completed";
                self.update_status("completed", COLOR_STATUS_COMPLETE)
                if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists(): self.progress_bar.config(
                    value=100, mode="determinate")
                downloads_dir = os.path.join(os.getcwd(),
                                             self.app_instance.settings['output_directory'])  # Use settings
                final_file_in_temp = os.path.join(downloads_dir, TEMP_SUBDIR, str(self.item_id),
                                                  self.filename + self.expected_final_ext)
                final_destination = os.path.join(downloads_dir, self.filename + self.expected_final_ext)
                if os.path.exists(final_file_in_temp):
                    try:
                        os.makedirs(downloads_dir, exist_ok=True)
                        shutil.move(final_file_in_temp, final_destination)
                        print(f"Moved final file from '{final_file_in_temp}' to '{final_destination}'")
                    except Exception as move_error:
                        print(f"Error moving final file: {move_error}")
                        self.app_instance.master.after(0, lambda: messagebox.showwarning("File Move Warning",
                                                                                         f"Conversion completed but could not move final file to downloads folder:\n{move_error}\nFile might be in temporary folder: {final_file_in_temp}"))
                else:
                    print(f"Final file not found in temp directory: {final_file_in_temp}")
                    self.app_instance.master.after(0, lambda: messagebox.showwarning("File Not Found",
                                                                                     f"Final converted file was not found where expected in temp folder: {final_file_in_temp}"))
            else:
                final_status = "failed";
                self.update_status("failed", COLOR_STATUS_FAILED)
        except FileNotFoundError:
            final_status = "failed";
            self.update_status("failed", COLOR_STATUS_FAILED)
            tool_name = "ffmpeg.exe" if is_ffmpeg_process else "yt-dlp.exe"
            if self.app_instance.log_window_visible and self.app_instance.log_text: self.app_instance.master.after(0,
                                                                                                                   lambda: self._append_to_log(
                                                                                                                       f"ERROR: {tool_name} not found or not in PATH.\n"))
            print(f"FileNotFoundError: {tool_name} not found or not in PATH for {self.source_path}")
        except Exception as e:
            final_status = "failed";
            self.update_status("failed", COLOR_STATUS_FAILED)
            if self.app_instance.log_window_visible and self.app_instance.log_text: self.app_instance.master.after(0,
                                                                                                                   lambda: self._append_to_log(
                                                                                                                       f"ERROR during execution: {e}\n"))
            print(f"Error during execution for {self.source_path}: {e}")
        finally:
            self.process = None
            if self.abort_button.winfo_exists(): self.abort_button.config(state="disabled")
            downloads_dir = os.path.join(os.getcwd(), self.app_instance.settings['output_directory'])  # Use settings
            temp_path = os.path.join(downloads_dir, TEMP_SUBDIR, str(self.item_id))
            if os.path.exists(temp_path): shutil.rmtree(temp_path, ignore_errors=True)
            self.app_instance.download_finished(self, final_status)

    def _append_to_log(self, text):
        """Appends text to the log window's ScrolledText widget."""
        if self.app_instance.log_text and self.app_instance.log_window.winfo_exists():
            self.app_instance.log_text.config(state=tk.NORMAL)
            self.app_instance.log_text.insert(END, text)
            self.app_instance.log_text.see(END)
            self.app_instance.log_text.config(state=tk.DISABLED)

    def _parse_output_for_progress(self, line):
        """Parses a line of yt-dlp output for progress, speed, and ETA."""
        match_percent = re.search(
            r'\[download\]\s+(\d+\.\d+)%|^[A-Za-z]+\s+.*?(\d+\.\d+)%\s+at\s+.*?(?:ETA\s+(\d{2}:\d{2}))?', line)
        if match_percent:
            percent_str = match_percent.group(1) if match_percent.group(1) else match_percent.group(2)
            if percent_str:
                percent = float(percent_str)
                if self.is_merging:
                    if hasattr(self,
                               'progress_bar') and self.progress_bar.winfo_exists(): self.progress_bar.stop(); self.progress_bar.config(
                        mode="determinate")
                    self.is_merging = False
                if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists(): self.progress_bar.config(
                    value=percent)
                speed_match = re.search(r'at\s+([0-9\.]+[KMG]?iB/s|\S+)(?:\s+ETA\s+(\d{2}:\d{2}))?', line)
                speed = speed_match.group(1) if speed_match and speed_match.group(1) else 'N/A'
                eta = speed_match.group(2) if speed_match and speed_match.group(2) else 'N/A'
                self.update_status(f"{percent:.1f}% ({speed}, ETA {eta})", COLOR_STATUS_PROGRESS)
            return
        if "merging formats" in line.lower() or "ffmpeg" in line.lower() or "postprocessing" in line.lower() or "extractaudio" in line.lower():
            if not self.is_merging:
                self.update_status("Converting/Merging...", COLOR_STATUS_PROGRESS)
                if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists(): self.progress_bar.config(
                    mode="indeterminate"); self.progress_bar.start()
                self.is_merging = True
            return
        if "downloading" in line.lower() and not self.is_merging:
            self.update_status("Downloading...", COLOR_STATUS_PROGRESS)
            return

    def _parse_ffmpeg_output_for_progress(self, line):
        """Parses a line of FFmpeg output for progress."""
        time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
        speed_match = re.search(r'speed=\s*([0-9\.]+)x', line)
        if time_match:
            hours = int(time_match.group(1));
            minutes = int(time_match.group(2));
            seconds = int(time_match.group(3))
            current_time_seconds = hours * 3600 + minutes * 60 + seconds
            speed_str = f"{speed_match.group(1)}x" if speed_match else "N/A"
            self.update_status(
                f"Converting... ({self._format_seconds_to_dd_hh_mm_ss(current_time_seconds)}, Speed: {speed_str})",
                COLOR_STATUS_PROGRESS)
            if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists() and self.progress_bar[
                'mode'] != "indeterminate":
                self.progress_bar.config(mode="indeterminate");
                self.progress_bar.start()
            self.is_merging = True
        elif "video:" in line or "audio:" in line and "global headers" in line:
            self.update_status("Converting...", COLOR_STATUS_PROGRESS)
            if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists() and self.progress_bar[
                'mode'] != "indeterminate":
                self.progress_bar.config(mode="indeterminate");
                self.progress_bar.start()
            self.is_merging = True

    def update_status(self, text, color):
        """Updates the status label for this download item."""
        if self.status_label.winfo_exists(): self.status_label.config(text=text.capitalize(), fg=color)
        self.status = text

    def abort_download(self):
        """Aborts the currently running download process."""
        self.is_aborted = True
        if self.process:
            try:
                self.process.kill()
                self.update_status("aborted", COLOR_STATUS_ABORTED)
                if self.is_merging:
                    if hasattr(self,
                               'progress_bar') and self.progress_bar.winfo_exists(): self.progress_bar.stop(); self.progress_bar.config(
                        mode="determinate")
            except Exception:
                self.update_status("failed", COLOR_STATUS_FAILED)
        else:
            self.update_status("aborted", COLOR_STATUS_ABORTED)
            self.app_instance.remove_from_queue(self)

    def retry_download(self):
        """Resets the item and re-add it to the queue for retry."""
        self.status = "queued";
        self.date_completed = 'N/A';
        self.elapsed_time_seconds = 0
        self.start_time = None;
        self.is_aborted = False;
        self.is_merging = False
        self.is_active_item = True;
        self.ready_for_download = True
        self.app_instance.queued_downloads.insert(0, self)
        self.app_instance._set_status(f"Retrying download for '{self.video_title}'.", COLOR_STATUS_READY)
        self.app_instance._refresh_display_order()  # Refresh display after adding to queue

    def _open_file_location(self):
        """Opens the folder containing the downloaded file and highlights the file."""
        expected_ext = ".mp4" if self.is_local_conversion else (".mp3" if self.mp3_conversion else ".mp4")
        downloads_dir = os.path.join(os.getcwd(), self.app_instance.settings['output_directory'])  # Use settings
        full_filepath = os.path.join(downloads_dir, self.filename + expected_ext)
        if not os.path.exists(full_filepath):
            messagebox.showerror("File Not Found", f"The file could not be found:\n{full_filepath}")
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(f'explorer /select,"{full_filepath.replace("/", "\\")}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", full_filepath])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(full_filepath)])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open file location: {e}")

    def _confirm_and_remove(self):
        """
        Opens a confirmation dialog for removing a download item,
        with options to delete the file and remember the choice.
        """
        # Check if "Don't show this again" is active and apply remembered choice
        if self.app_instance.settings['remember_delete_choice']:
            delete_file = self.app_instance.settings['delete_file_on_remove']
            self.app_instance._remove_item_from_list_and_disk(self, delete_file)
            return

        confirm_win = tk.Toplevel(self.app_instance.master)
        confirm_win.title("Confirm Removal")
        confirm_win.geometry("400x180")
        confirm_win.transient(self.app_instance.master)
        confirm_win.grab_set()
        confirm_win.resizable(False, False)

        tk.Label(confirm_win, text=f"Are you sure you want to remove '{self.video_title}'?",
                 font=MAIN_FONT, wraplength=350).pack(pady=10)

        delete_file_var = tk.BooleanVar(
            value=self.app_instance.settings['delete_file_on_remove_default'])  # Initialize with default setting
        remember_delete_choice_var = tk.BooleanVar(value=False)  # Always starts unchecked for the dialog itself

        tk.Checkbutton(confirm_win, text="Also delete file from disk?", variable=delete_file_var,
                       font=SMALL_FONT).pack(anchor="w", padx=20)
        tk.Checkbutton(confirm_win, text="Don't show this again (remember my choice)", variable=remember_delete_choice_var,
                       font=SMALL_FONT).pack(anchor="w", padx=20)

        def on_yes():
            delete_file = delete_file_var.get()
            if remember_delete_choice_var.get():
                self.app_instance.settings['remember_delete_choice'] = True
                self.app_instance.settings['delete_file_on_remove'] = delete_file
                self.app_instance.settings[
                    'delete_file_on_remove_default'] = delete_file  # Update default for next time
                self.app_instance._save_settings()  # Save this preference immediately
            confirm_win.destroy()
            self.app_instance._remove_item_from_list_and_disk(self, delete_file)

        def on_no():
            confirm_win.destroy()

        button_frame = tk.Frame(confirm_win)
        button_frame.pack(pady=10)

        tk.Button(button_frame, text="Yes", command=on_yes, bg=COLOR_ABORT_BUTTON, fg="white", font=SMALL_FONT,
                  width=8).pack(side="left", padx=5)
        tk.Button(button_frame, text="No", command=on_no, bg=COLOR_ADD_BUTTON, fg="white", font=SMALL_FONT,
                  width=8).pack(side="left", padx=5)

        confirm_win.protocol("WM_DELETE_WINDOW", on_no)  # Handle window close button
        confirm_win.wait_window()


class YTDLPGUIApp:
    def __init__(self, master):
        self.master = master

        # Initialize log_window and log_text early to ensure they always exist as attributes
        self.log_window = None
        self.log_text = None

        # Load settings first
        self.settings = self._load_settings()

        # Initialize log_toggle_var and log_window_visible based on settings
        self.log_toggle_var = tk.BooleanVar(value=self.settings['show_log_window'])
        self.log_window_visible = self.settings['show_log_window']

        self._setup_window(master)
        self._configure_yt_dlp_path()
        self._create_menus()  # Now self.log_toggle_var and self.log_window exist when this is called
        self._create_widgets()
        self._initialize_download_management()
        self._cleanup_temp_directories_on_launch()
        self._load_downloads_from_local_history()

        self.master.after(100, self._process_queue_loop)
        # Initialize UI state based on default source (Default) and settings
        self.on_source_change(DEFAULT_SOURCE)
        self.master.after_idle(self._refresh_display_order)

        self.selected_local_filepath = None

    def _get_default_settings(self):
        return {
            "show_log_window": False,
            "max_concurrent_downloads": DEFAULT_MAX_CONCURRENT_DOWNLOADS,
            "output_directory": DEFAULT_DOWNLOADS_DIR,
            "default_default_quality": "Auto (Best available)",
            "default_local_quality": "Medium Quality MP4",
            "remember_delete_choice": False,  # New setting: if True, skips confirmation dialog
            "delete_file_on_remove": False,
            # New setting: stores the remembered choice (if remember_delete_choice is True)
            "delete_file_on_remove_default": False  # New setting: default for 'also delete file' checkbox in dialog
        }

    def _load_settings(self):
        settings = self._get_default_settings()
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                    # Update defaults with loaded settings, ensuring new keys are added
                    for key, value in loaded_settings.items():
                        if key in settings:  # Only update if key exists in default settings
                            settings[key] = value

                    # Handle renaming of default_youtube_quality to default_default_quality
                    if 'default_youtube_quality' in loaded_settings and 'default_default_quality' not in loaded_settings:
                        settings['default_default_quality'] = loaded_settings['default_youtube_quality']
                        # No need to del, as we only copy existing keys into settings
            except (IOError, json.JSONDecodeError) as e:
                print(f"Error loading settings from {CONFIG_FILE}: {e}")
                messagebox.showwarning("Settings Load Error",
                                       f"Could not load settings. Resetting to default. Error: {e}")
                # Optionally, delete corrupted config file
                if os.path.exists(CONFIG_FILE):
                    os.remove(CONFIG_FILE)

        # Ensure output directory exists based on loaded/default setting
        full_output_path = os.path.join(os.getcwd(), settings['output_directory'])
        os.makedirs(full_output_path, exist_ok=True)

        return settings

    def _save_settings(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4)
            return True
        except IOError as e:
            messagebox.showerror("Settings Save Error", f"Failed to save settings: {e}")
            return False

    def _setup_window(self, master):
        master.title("Universal Video Downloader & Converter")
        master.geometry("1000x650")
        master.resizable(False, False)
        master.minsize(1000, 650)
        master.maxsize(1000, 650)
        try:
            master.iconbitmap("ico.ico")
        except Exception:
            pass

    def _create_menus(self):
        """Creates the application menus."""
        menubar = tk.Menu(self.master)
        self.master.config(menu=menubar)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About Versions...", command=self._show_versions_info)

        options_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Options", menu=options_menu)
        options_menu.add_command(label="Settings", command=self._create_settings_window)

        # The 'View' menu part that toggles log window
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        # self.log_toggle_var is initialized in __init__ based on settings
        view_menu.add_checkbutton(label="Show Process Log", variable=self.log_toggle_var,
                                  command=self._toggle_log_window)

        # Initial call to open log window if setting is true (moved from __init__)
        if self.log_toggle_var.get():
            self._toggle_log_window()

    def _create_settings_window(self):
        settings_win = tk.Toplevel(self.master)
        settings_win.title("Settings")
        settings_win.geometry("500x400")  # Increased height for new options
        settings_win.transient(self.master)  # Make it appear on top of the main window
        settings_win.grab_set()  # Make it modal
        settings_win.resizable(False, False)

        settings_frame = ttk.Frame(settings_win, padding="10")
        settings_frame.pack(fill="both", expand=True)
        settings_frame.columnconfigure(1, weight=1)

        # Variables for settings window widgets
        max_downloads_var = tk.IntVar(value=self.settings['max_concurrent_downloads'])
        output_dir_var = tk.StringVar(value=self.settings['output_directory'])
        show_log_var = tk.BooleanVar(value=self.settings['show_log_window'])
        default_default_quality_var = tk.StringVar(value=self.settings['default_default_quality'])
        default_local_quality_var = tk.StringVar(value=self.settings['default_local_quality'])

        # New variables for removal settings
        remember_delete_choice_var = tk.BooleanVar(value=self.settings['remember_delete_choice'])
        delete_file_on_remove_var = tk.BooleanVar(value=self.settings['delete_file_on_remove'])
        delete_file_on_remove_default_var = tk.BooleanVar(value=self.settings['delete_file_on_remove_default'])

        # Max Concurrent Downloads
        ttk.Label(settings_frame, text="Max Concurrent Downloads:").grid(row=0, column=0, sticky="w", pady=5)
        max_downloads_spinbox = ttk.Spinbox(settings_frame, from_=1, to=5, textvariable=max_downloads_var, width=5)
        max_downloads_spinbox.grid(row=0, column=1, sticky="w", pady=5)

        # Output Directory
        ttk.Label(settings_frame, text="Output Directory:").grid(row=1, column=0, sticky="w", pady=5)
        output_dir_entry = ttk.Entry(settings_frame, textvariable=output_dir_var)
        output_dir_entry.grid(row=1, column=1, sticky="ew", pady=5, padx=(0, 5))
        ttk.Button(settings_frame, text="Browse", command=lambda: self._browse_output_directory(output_dir_var)).grid(
            row=1, column=2, sticky="e", pady=5)

        # Show Log Window by default
        ttk.Checkbutton(settings_frame, text="Show Process Log on Startup", variable=show_log_var).grid(row=2, column=0,
                                                                                                        columnspan=2,
                                                                                                        sticky="w",
                                                                                                        pady=5)

        # Default Default Quality (formerly YouTube)
        ttk.Label(settings_frame, text="Default Source Quality:").grid(row=3, column=0, sticky="w", pady=5)
        default_quality_options = ["Auto (Best available)", "High Quality - 1080p", "Medium Quality - 720p",
                                   "Low Quality - 480p"]
        default_quality_menu = ttk.OptionMenu(settings_frame, default_default_quality_var,
                                              default_default_quality_var.get(), *default_quality_options)
        default_quality_menu.grid(row=3, column=1, sticky="ew", pady=5)

        # Default Local Quality
        ttk.Label(settings_frame, text="Default Local Conversion Quality:").grid(row=4, column=0, sticky="w", pady=5)
        local_quality_options = ["Same as source", "High Quality MP4", "Medium Quality MP4", "Low Quality MP4"]
        local_quality_menu = ttk.OptionMenu(settings_frame, default_local_quality_var, default_local_quality_var.get(),
                                            *local_quality_options)
        local_quality_menu.grid(row=4, column=1, sticky="ew", pady=5)

        # New: Remove Confirmation Settings
        ttk.Label(settings_frame, text="Remove Entry Options:", font=BOLD_FONT).grid(row=5, column=0, columnspan=3,
                                                                                     sticky="w", pady=(15, 5))

        # "Don't show this again" checkbox
        remember_choice_checkbox = ttk.Checkbutton(settings_frame, text="Don't show removal confirmation dialog",
                                                   variable=remember_delete_choice_var)
        remember_choice_checkbox.grid(row=6, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # "Automatically delete file on remove" checkbox (only active if "Don't show this again" is checked)
        delete_file_on_remove_checkbox = ttk.Checkbutton(settings_frame,
                                                         text="Automatically delete file when removing entry",
                                                         variable=delete_file_on_remove_var)
        delete_file_on_remove_checkbox.grid(row=7, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # Default state for "Also delete file?" checkbox in the dialog
        delete_file_on_remove_default_checkbox = ttk.Checkbutton(settings_frame,
                                                                 text="Default: 'Also delete file?' checked",
                                                                 variable=delete_file_on_remove_default_var)
        delete_file_on_remove_default_checkbox.grid(row=8, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # Function to enable/disable delete_file_on_remove_checkbox
        def toggle_delete_file_checkbox_state():
            if remember_delete_choice_var.get():
                delete_file_on_remove_checkbox.config(state="normal")
            else:
                delete_file_on_remove_checkbox.config(state="disabled")
                # When "Don't show this again" is unchecked, the 'delete_file_on_remove' setting is irrelevant
                # for *automatic* deletion, but its value should persist for when 'remember_choice' is re-enabled.
                # However, for clarity in the UI, we can uncheck it if the main "remember" is off.
                # The actual remembered value is saved in self.settings['delete_file_on_remove']
                # when the user clicks 'Yes' and 'Don't show this again'.
                delete_file_on_remove_var.set(False)  # Uncheck when disabled for clearer UI feedback

        remember_delete_choice_var.trace_add("write", lambda *args: toggle_delete_file_checkbox_state())
        # Initial call to set state correctly on window open
        toggle_delete_file_checkbox_state()

        def apply_settings():
            try:
                self.settings['max_concurrent_downloads'] = max_downloads_var.get()

                # Validate output directory path. Use relative path if possible.
                new_output_dir = output_dir_var.get().strip()
                if not new_output_dir:
                    messagebox.showwarning("Invalid Path", "Output directory cannot be empty. Reverting to default.")
                    new_output_dir = DEFAULT_DOWNLOADS_DIR
                    output_dir_var.set(new_output_dir)

                # Ensure path is relative if it's within current working directory, otherwise keep as absolute
                if os.path.isabs(new_output_dir):
                    try:
                        relative_path = os.path.relpath(new_output_dir, os.getcwd())
                        # If relative path is shorter or dot-relative, use it
                        if len(relative_path) < len(new_output_dir) or relative_path.startswith('.'):
                            self.settings['output_directory'] = relative_path
                        else:
                            self.settings['output_directory'] = new_output_dir
                    except ValueError:  # Occurs if paths are on different drives
                        self.settings['output_directory'] = new_output_dir
                else:
                    self.settings['output_directory'] = new_output_dir

                # Create the directory if it doesn't exist
                full_path_to_create = os.path.join(os.getcwd(), self.settings['output_directory'])
                os.makedirs(full_path_to_create, exist_ok=True)

                self.settings['show_log_window'] = show_log_var.get()
                self.settings['default_default_quality'] = default_default_quality_var.get()
                self.settings['default_local_quality'] = default_local_quality_var.get()

                # Save new removal settings
                self.settings['remember_delete_choice'] = remember_delete_choice_var.get()
                self.settings['delete_file_on_remove'] = delete_file_on_remove_var.get()
                self.settings['delete_file_on_remove_default'] = delete_file_on_remove_default_var.get()

                # Apply log window setting immediately
                self.log_toggle_var.set(self.settings['show_log_window'])
                self.log_window_visible = self.settings['show_log_window']

                # Ensure the log window state is updated
                if self.log_window_visible:
                    self._toggle_log_window()
                else:
                    self._on_log_window_close()

                messagebox.showinfo("Settings Applied",
                                    "Settings applied successfully. Remember to click 'Save' to make them permanent.")
            except Exception as e:
                messagebox.showerror("Error Applying Settings", f"An error occurred: {e}")

        def save_and_close():
            apply_settings()  # Apply current changes before saving
            if self._save_settings():
                settings_win.destroy()
                # Update main window's default qualities immediately after saving
                self.quality_var.set(self.settings['default_default_quality'])
                self.local_quality_var.set(self.settings['default_local_quality'])
                self._set_status("Settings saved and applied.", COLOR_STATUS_COMPLETE)
            else:
                self._set_status("Failed to save settings.", COLOR_STATUS_FAILED)

        def cancel_and_close():
            settings_win.destroy()

        # Buttons
        button_frame = ttk.Frame(settings_win)
        button_frame.pack(side="bottom", fill="x", pady=10)

        ttk.Button(button_frame, text="Apply", command=apply_settings).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Save & Close", command=save_and_close).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=cancel_and_close).pack(side="right", padx=5)

        settings_win.protocol("WM_DELETE_WINDOW", cancel_and_close)  # Handle window close button
        self.master.wait_window(settings_win)  # Wait for settings window to close

    def _browse_output_directory(self, output_dir_var):
        selected_dir = filedialog.askdirectory(
            title="Select Output Directory",
            initialdir=os.path.join(os.getcwd(), output_dir_var.get())  # Use current setting as initial
        )
        if selected_dir:
            output_dir_var.set(selected_dir)

    def _show_versions_info(self):
        """Displays yt-dlp and ffmpeg version information."""
        yt_dlp_version = "Not Found";
        ffmpeg_version = "Not Found"
        try:
            yt_dlp_result = subprocess.run([self.yt_dlp_path, "--version"], capture_output=True, text=True, check=True,
                                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                                           timeout=5)
            yt_dlp_version = yt_dlp_result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        try:
            ffmpeg_result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True,
                                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                                           timeout=5)
            ffmpeg_version_lines = ffmpeg_result.stdout.strip().split('\n')
            if ffmpeg_version_lines: ffmpeg_version = ffmpeg_version_lines[0]
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        messagebox.showinfo("About Versions",
                            f"yt-dlp Version: {yt_dlp_version}\nFFmpeg Version: {ffmpeg_version}\n\nThis application uses yt-dlp for downloading and FFmpeg for media processing.")

    def _toggle_log_window(self):
        """Toggles the visibility of the process log window."""
        self.log_window_visible = self.log_toggle_var.get()
        if self.log_window_visible:
            if not self.log_window or not self.log_window.winfo_exists():
                self.log_window = tk.Toplevel(self.master)
                self.log_window.title("Process Log")
                self.log_window.geometry("600x400")
                self.log_window.protocol("WM_DELETE_WINDOW", self._on_log_window_close)
                self.log_text = scrolledtext.ScrolledText(self.log_window, wrap=tk.WORD, font=MONO_FONT, bg="black",
                                                          fg="lightgreen", insertbackground="white")
                self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
                self.log_text.config(state=tk.DISABLED)
            self.log_window.deiconify()
        else:
            if self.log_window and self.log_window.winfo_exists(): self.log_window.withdraw()

    def _on_log_window_close(self):
        """Handles the log window close button, updating the toggle variable."""
        self.log_toggle_var.set(False)
        self.log_window_visible = False
        if self.log_window: self.log_window.withdraw()

    def _open_downloads_folder(self):
        """Opens the main downloads directory."""
        downloads_path = os.path.join(os.getcwd(), self.settings['output_directory'])  # Use setting
        if not os.path.exists(downloads_path): os.makedirs(downloads_path, exist_ok=True)
        try:
            # On Windows, os.startfile opens the folder. On macOS/Linux, xdg-open/open.
            if sys.platform == "win32":
                os.startfile(downloads_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", downloads_path])
            else:
                subprocess.Popen(["xdg-open", downloads_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open downloads folder: {e}")

    def _create_widgets(self):
        self.main_frame = tk.Frame(self.master, padx=10, pady=10)
        self.main_frame.pack(fill="both", expand=True)
        self.main_frame.grid_columnconfigure(1, weight=1)

        input_frame = tk.LabelFrame(self.main_frame, text="Add New Download/Conversion", font=MAIN_FONT, padx=10,
                                    pady=10)
        input_frame.pack(fill="x", pady=5)
        input_frame.columnconfigure(1, weight=1)

        # Source Selection (Row 0)
        tk.Label(input_frame, text="Source:", font=MAIN_FONT).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.source_var = tk.StringVar(value=DEFAULT_SOURCE)
        self.source_menu = tk.OptionMenu(input_frame, self.source_var, DEFAULT_SOURCE, XTREAM_SOURCE, LOCAL_SOURCE,
                                         command=self.on_source_change)
        self.source_menu.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        self.master.update_idletasks()  # Force update after gridding OptionMenu

        # Dynamic Input Fields Container (Rows 1 onwards)
        self.dynamic_input_container = tk.Frame(input_frame)
        self.dynamic_input_container.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.dynamic_input_container.columnconfigure(1, weight=1)

        # Common input widgets (initialized but not gridded directly, will be placed in dynamic_input_container)
        self.url_label = tk.Label(self.dynamic_input_container, text="Target URL:", font=MAIN_FONT)
        self.url_entry = tk.Entry(self.dynamic_input_container, font=MAIN_FONT)
        self.referer_label = tk.Label(self.dynamic_input_container, text="Referer URL:", font=MAIN_FONT)
        self.referer_entry = tk.Entry(self.dynamic_input_container, font=MAIN_FONT)
        self.local_filepath_label = tk.Label(self.dynamic_input_container, text="No file selected", font=MAIN_FONT,
                                             anchor="w", wraplength=400)
        self.browse_file_button = tk.Button(self.dynamic_input_container, text="Browse Local File",
                                            command=self._browse_local_file, bg=COLOR_BROWSE_FILE_BUTTON, fg="white",
                                            font=SMALL_FONT, width=15)

        # Initialize quality_var with default setting
        self.quality_var = tk.StringVar(value=self.settings['default_default_quality'])
        self.quality_label = tk.Label(self.dynamic_input_container, text="Quality:", font=MAIN_FONT)
        self.quality_menu = tk.OptionMenu(self.dynamic_input_container, self.quality_var,
                                          "Auto (Best available)")  # Options will be updated by _update_quality_options_grouped

        # Initialize local_quality_var with default setting
        self.local_quality_var = tk.StringVar(value=self.settings['default_local_quality'])
        self.local_quality_label = tk.Label(self.dynamic_input_container, text="Output Quality:", font=MAIN_FONT)
        self.local_quality_menu = tk.OptionMenu(self.dynamic_input_container, self.local_quality_var, "Same as source",
                                                "High Quality MP4", "Medium Quality MP4", "Low Quality MP4")

        # Output Filename (common for all sources, placed below dynamic inputs)
        tk.Label(input_frame, text="Output Filename (optional):", font=MAIN_FONT).grid(row=2, column=0, sticky="w",
                                                                                       padx=5, pady=2)
        self.filename_entry = tk.Entry(input_frame, font=MAIN_FONT)
        self.filename_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=2)

        # MP3 Conversion (common for online sources, placed below filename)
        self.mp3_var = tk.BooleanVar()
        self.mp3_check = tk.Checkbutton(input_frame, text="Convert to MP3 (for online sources)", variable=self.mp3_var,
                                        font=MAIN_FONT)
        self.mp3_check.grid(row=3, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # Add to Queue Button (Fixed position at the bottom of input_frame)
        self.add_to_queue_button = tk.Button(input_frame, text="Add to Queue", command=self._add_current_to_queue,
                                             bg=COLOR_ADD_BUTTON, fg="white", font=BOLD_FONT)
        self.add_to_queue_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=10)

        # Bind events
        self.url_entry.bind("<Return>", self._add_to_queue_on_enter)
        self.url_entry.bind("<FocusOut>", self._on_url_focus_out)

        control_buttons_frame = tk.Frame(self.main_frame)
        control_buttons_frame.pack(fill="x", pady=5)

        self.clear_queue_button = tk.Button(control_buttons_frame, text="Clear Queue", command=self._clear_queue,
                                            bg=COLOR_CLEAR_BUTTON, fg="black", font=BOLD_FONT)
        self.clear_queue_button.pack(side="left", expand=True, fill="x", padx=2)

        self.open_downloads_button = tk.Button(control_buttons_frame, text="Open Downloads",
                                               command=self._open_downloads_folder, bg=COLOR_OPEN_FOLDER_BUTTON,
                                               fg="white", font=BOLD_FONT)
        self.open_downloads_button.pack(side="left", expand=True, fill="x", padx=2)

        self.clear_history_button = tk.Button(control_buttons_frame, text="Clear History",
                                              command=self._clear_finished_history, bg=COLOR_CLEAR_BUTTON, fg="black",
                                              font=BOLD_FONT)
        self.clear_history_button.pack(side="left", expand=True, fill="x", padx=2)

        self.display_area_frame = tk.Frame(self.main_frame)
        self.display_area_frame.pack(fill="both", expand=True, pady=5)
        self.display_area_frame.grid_rowconfigure(0, weight=1)
        self.display_area_frame.grid_columnconfigure(0, weight=1)
        self.display_area_frame.grid_columnconfigure(1, weight=0)

        self.downloads_canvas = tk.Canvas(self.display_area_frame, bg="white", highlightthickness=0)
        self.downloads_canvas.grid(row=0, column=0, sticky="nsew")

        self.downloads_scroll_y = tk.Scrollbar(self.display_area_frame, orient="vertical",
                                               command=self.downloads_canvas.yview)
        self.downloads_scroll_y.grid(row=0, column=1, sticky="ns")

        self.downloads_canvas.config(yscrollcommand=self.downloads_scroll_y.set)

        self.downloads_frame_inner = tk.Frame(self.downloads_canvas, bg="white")
        self.downloads_canvas_window_id = self.downloads_canvas.create_window((0, 0), window=self.downloads_frame_inner,
                                                                              anchor="nw", width=0)

        self.downloads_frame_inner.bind("<Configure>", lambda e: self.downloads_canvas.configure(
            scrollregion=self.downloads_canvas.bbox("all")))
        self.downloads_canvas.bind('<Configure>', self._on_downloads_canvas_resize)

        self.downloads_canvas.bind('<MouseWheel>', self._on_mousewheel)
        self.downloads_canvas.bind('<Button-4>', self._on_mousewheel)
        self.downloads_canvas.bind('<Button-5>', self._on_mousewheel)

        self.status_bar = tk.Label(self.master, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W, font=SMALL_FONT,
                                   fg=COLOR_STATUS_READY)
        self.status_bar.pack(side="bottom", fill="x")

    def _on_mousewheel(self, event):
        """Handles mouse wheel scrolling for the combined downloads canvas."""
        self.downloads_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _on_downloads_canvas_resize(self, event):
        """Adjusts the width of the inner frame when the canvas resizes."""
        self.downloads_canvas.itemconfig(self.downloads_canvas_window_id, width=event.width)
        self.downloads_canvas.configure(scrollregion=self.downloads_canvas.bbox("all"))
        self._refresh_display_order()

    def _initialize_download_management(self):
        self.queued_downloads = []
        self.active_downloads = []
        self.download_items_map = {}
        self.download_item_counter = 0
        self.completed_downloads_count = 0
        self.total_downloads_added = 0
        self.is_queue_processing_active = False
        self.all_downloads_completed = threading.Event()
        self.alert_on_completion_for_session = False

    def _configure_yt_dlp_path(self):
        if hasattr(sys, '_MEIPASS'):
            self.yt_dlp_path = os.path.join(sys._MEIPASS, 'yt-dlp.exe')
        else:
            self.yt_dlp_path = 'yt-dlp.exe'

    def on_source_change(self, value):
        """Adjusts UI based on selected source (Default, XtremeStream, or Local)."""
        # Clear previous dynamic inputs in the container
        for widget in self.dynamic_input_container.winfo_children():
            widget.grid_forget()

        current_row_idx = 0  # Start from row 0 within the dynamic_input_container

        if value == DEFAULT_SOURCE:
            self.url_label.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.url_entry.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            current_row_idx += 1
            self._update_quality_options_grouped(
                [("Auto (Best available)", "Auto (Best available)")], [], [], [],
                [("1080", "High Quality - 1080p")], [("720", "Medium Quality - 720p")], [("480", "Low Quality - 480p")]
            )
            self.quality_label.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.quality_menu.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            self.url_entry.bind("<Return>", self._add_to_queue_on_enter)
            self.url_entry.bind("<FocusOut>", self._on_url_focus_out)
            self.mp3_check.config(state="normal")
            # Set default quality from settings
            self.quality_var.set(self.settings['default_default_quality'])


        elif value == XTREAM_SOURCE:
            self.referer_label.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.referer_entry.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            current_row_idx += 1
            self.url_label.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.url_entry.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            self._update_quality_options_grouped([("Auto (Best available)", "Auto (Best available)")], [], [], [], [],
                                                 [], [])
            self.quality_label.grid(row=current_row_idx + 1, column=0, sticky="w", padx=5, pady=2)
            self.quality_menu.grid(row=current_row_idx + 1, column=1, sticky="ew", padx=5, pady=2)
            self.url_entry.bind("<Return>", self._add_to_queue_on_enter)
            self.url_entry.bind("<FocusOut>", self._on_url_focus_out)
            self.mp3_check.config(state="normal")
            # Set default quality from settings (it's "Auto" for XtremeStream anyway)
            self.quality_var.set(self.settings['default_default_quality'])


        elif value == LOCAL_SOURCE:
            self.url_entry.unbind("<Return>")
            self.url_entry.unbind("<FocusOut>")

            self.browse_file_button.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.local_filepath_label.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            current_row_idx += 1
            self.local_quality_label.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.local_quality_menu.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            self.mp3_check.config(state="disabled")
            self.mp3_var.set(False)
            # Set default quality from settings
            self.local_quality_var.set(self.settings['default_local_quality'])

        # Always ensure common input fields are cleared/reset when source changes
        self.url_entry.delete(0, END)
        self.referer_entry.delete(0, END)
        self.local_filepath_label.config(text="No file selected")
        self.selected_local_filepath = None
        self.filename_entry.delete(0, END)  # Clear filename entry explicitly

        self.url_entry.focus_set()  # Set focus back to URL entry for convenience

        # Update the overall frame sizing after dynamic widget changes
        self.dynamic_input_container.update_idletasks()
        self.master.update_idletasks()

    def _set_status(self, text, color="black"):
        """Updates the main status bar."""
        self.status_bar.config(text=text, fg=color)

    def _browse_output_directory(self, output_dir_var):
        selected_dir = filedialog.askdirectory(
            title="Select Output Directory",
            initialdir=os.path.join(os.getcwd(), output_dir_var.get())  # Use current setting as initial
        )
        if selected_dir:
            output_dir_var.set(selected_dir)

    def _browse_local_file(self):
        """Opens a file dialog to select a local video file for conversion."""
        filepath = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[("Video files", "*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.webm"), ("All files", "*.*")]
        )
        if filepath:
            self.selected_local_filepath = filepath
            display_path = filepath
            if len(display_path) > 50: display_path = "..." + display_path[-47:]
            self.local_filepath_label.config(text=display_path)
            self.filename_entry.delete(0, END)
            self.filename_entry.insert(0, os.path.splitext(os.path.basename(filepath))[0])
        else:
            self.selected_local_filepath = None
            self.local_filepath_label.config(text="No file selected")
            self.filename_entry.delete(0, END)

    def _add_current_to_queue(self):
        """Adds the current input values as a new download/conversion item to the queue."""
        source = self.source_var.get()
        source_path = "";
        quality = "N/A";
        filename_for_item_data = self.filename_entry.get().strip()
        filename_provided_by_user = bool(filename_for_item_data)
        mp3_conversion = self.mp3_var.get()
        referer = ""
        video_title = 'Fetching Title...'

        if source == LOCAL_SOURCE:
            source_path = self.selected_local_filepath
            if not source_path or not os.path.exists(source_path): messagebox.showwarning("Input Error",
                                                                                          "Please select a local video file."); return
            quality = self.local_quality_var.get()
            mp3_conversion = False
            if not filename_for_item_data: filename_for_item_data = os.path.splitext(os.path.basename(source_path))[0]
            video_title = os.path.basename(source_path)
        else:
            source_path = self.url_entry.get().strip()
            if not source_path: messagebox.showwarning("Input Error", "Target URL is required."); return
            if not (source_path.startswith("http://") or source_path.startswith("https://")): messagebox.showwarning(
                "Input Error", "Invalid URL. Must start with http:// or https://"); return
            quality = self.quality_var.get()
            referer = self.referer_entry.get().strip() if source == XTREAM_SOURCE else ""

        self.download_item_counter += 1
        item_id = self.download_item_counter

        item_data = {
            'id': item_id, 'source_path': source_path, 'quality': quality, 'filename': filename_for_item_data,
            'mp3_conversion': mp3_conversion, 'source': source, 'referer': referer, 'video_title': video_title,
            'status': 'queued', 'date_added': time.strftime("%m/%d/%y"),
            'filename_provided_by_user': filename_provided_by_user,
            'elapsed_time_seconds': 0
        }

        new_item = DownloadItem(self, item_data, is_active_item=True)
        self.queued_downloads.append(new_item)
        self.download_items_map[item_id] = new_item
        self.total_downloads_added += 1
        self._refresh_display_order()
        self._set_status(f"Added '{source_path}' to queue.", COLOR_STATUS_READY)

        self.url_entry.delete(0, END);
        self.filename_entry.delete(0, END);
        self.mp3_var.set(False)
        self.referer_entry.delete(0, END);
        self.local_filepath_label.config(text="No file selected");
        self.selected_local_filepath = None
        self.url_entry.focus_set()
        self.alert_on_completion_for_session = True

    def _add_to_queue_on_enter(self, event=None):
        """Handles adding to queue when Enter is pressed in URL entry."""
        if self.source_var.get() != LOCAL_SOURCE: self._add_current_to_queue()

    def _on_url_focus_out(self, event=None):
        """Attempts to pre-fill filename based on URL if not provided by user and source is Default/XtremeStream."""
        if self.source_var.get() == LOCAL_SOURCE: return
        url = self.url_entry.get().strip()
        if url and not self.filename_entry.get().strip():
            temp_item_data = {
                'id': -1, 'source_path': url, 'quality': self.quality_var.get(), 'filename': '',
                'mp3_conversion': self.mp3_var.get(), 'source': self.source_var.get(),
                'referer': self.referer_entry.get().strip(),
                'video_title': 'Fetching Title...', 'status': 'temp_fetching', 'date_added': 'N/A',
                'filename_provided_by_user': False, 'elapsed_time_seconds': 0
            }
            temp_item = DownloadItem(self, temp_item_data, is_active_item=True)

            def _update_filename_after_fetch():
                if not self.filename_entry.get().strip():
                    if temp_item.is_title_fetched and temp_item.video_title not in ['Unknown Title',
                                                                                    'Fetching Title...']:
                        sanitized_title = re.sub(r'[\\/:*?"<>|]', '', temp_item.video_title)
                        self.filename_entry.delete(0, END)
                        preview_filename = sanitized_title[:60] if len(sanitized_title) > 60 else sanitized_title
                        self.filename_entry.insert(0, preview_filename)
                    else:
                        self.filename_entry.delete(0, END)
                        self.filename_entry.insert(0, f"VideoPlayback_Preview")

            threading.Thread(
                target=lambda: (temp_item.fetch_title_async(), self.master.after(500, _update_filename_after_fetch)),
                daemon=True).start()

    def _update_quality_options_grouped(self, auto, combined_video_audio, combined_audio_only, video_only,
                                        high_quality_video, medium_quality_video, low_quality_video):
        """Updates the quality OptionMenu with new options based on source."""
        menu = self.quality_menu["menu"];
        menu.delete(0, "end")

        def add_command(value):
            menu.add_command(label=value, command=tk._setit(self.quality_var, value))

        if auto:
            for text, val in auto: add_command(text)
            menu.add_separator()
        if combined_video_audio:
            menu.add_command(label="--- Combined Video + Audio ---", state="disabled")
            for res, text in combined_video_audio: add_command(f"{text} - {res}p")
            menu.add_separator()
        if combined_audio_only:
            menu.add_command(label="--- Combined Audio Only ---", state="disabled")
            for res, text in combined_audio_only: add_command(f"{text} - {res}p")
            menu.add_separator()
        if video_only:
            menu.add_command(label="--- Video Only ---", state="disabled")
            for res, text in video_only: add_command(f"{text}")
            menu.add_separator()
        if high_quality_video:
            menu.add_command(label="--- High Quality Video ---", state="disabled")
            for res, text in high_quality_video: add_command(f"{text}")
            menu.add_separator()
        if medium_quality_video:
            menu.add_command(label="--- Medium Quality Video ---", state="disabled")
            for res, text in medium_quality_video: add_command(f"{text}")
            menu.add_separator()
        if low_quality_video:
            menu.add_command(label="--- Low Quality Video ---", state="disabled")
            for res, text in low_quality_video: add_command(f"{text}")

        # Ensure the selected value is still in the list of options, otherwise reset to default
        if self.quality_var.get() not in [item[0] for item in
                                          auto + combined_video_audio + combined_audio_only + video_only + high_quality_video + medium_quality_video + low_quality_video]:
            if auto:
                self.quality_var.set(auto[0][0])
            else:
                self.quality_var.set("Auto (Best available)")

    def _process_queue_loop(self):
        """Manages the download queue, starting new downloads as slots become free."""
        active_count = len(self.active_downloads)
        # Use max_concurrent_downloads from settings
        max_concurrent = self.settings['max_concurrent_downloads']

        next_item_to_start = None
        for i, item in enumerate(self.queued_downloads):
            if item.ready_for_download:
                next_item_to_start = self.queued_downloads.pop(i);
                break
        if next_item_to_start and active_count < max_concurrent:  # Use max_concurrent
            self.active_downloads.append(next_item_to_start)
            self._set_status(f"Starting {next_item_to_start.source} for {next_item_to_start.video_title}...",
                             COLOR_STATUS_PROGRESS)
            next_item_to_start.start_download()
            self.is_queue_processing_active = True
            self.all_downloads_completed.clear()
        elif not self.active_downloads and not self.queued_downloads and self.is_queue_processing_active:
            self.is_queue_processing_active = False
            self.all_downloads_completed.set()
            if self.alert_on_completion_for_session and self.total_downloads_added > 0:
                messagebox.showinfo("Tasks Complete", f"All {self.completed_downloads_count} tasks finished!")
                self.alert_on_completion_for_session = False;
                self.completed_downloads_count = 0;
                self.total_downloads_added = 0
            self._set_status("All tasks finished. Ready.", COLOR_STATUS_COMPLETE)
        self.master.after(1000, self._process_queue_loop)

    def download_finished(self, item, final_status):
        """Called by a DownloadItem when its process completes (success/fail/abort)."""
        if item in self.active_downloads: self.active_downloads.remove(item)
        item.status = final_status
        item.date_completed = time.strftime("%m/%d/%y")
        if item.start_time:
            item.elapsed_time_seconds = int(time.time() - item.start_time)
        else:
            item.elapsed_time_seconds = 0
        item.is_active_item = False
        self._save_downloads_to_local_history()
        if final_status == "completed":
            self.completed_downloads_count += 1
            self._set_status(f"Task for '{item.video_title}' completed!", COLOR_STATUS_COMPLETE)
        elif final_status == "aborted":
            self._set_status(f"Task for '{item.video_title}' aborted.", COLOR_STATUS_ABORTED)
        else:
            self._set_status(f"Task for '{item.video_title}' failed.", COLOR_STATUS_FAILED)
        self._refresh_display_order()

    def _remove_item_from_list_and_disk(self, item_obj, delete_file_from_disk):
        """
        Removes a download item from the application's list and optionally deletes its associated file.
        """
        if item_obj.is_active_item:
            item_obj.abort_download()  # Abort if active, which will then call download_finished and remove it.
            # The item will be removed from download_items_map and history saved by download_finished
        else:
            # If not active, remove directly from map and save history
            if item_obj.item_id in self.download_items_map:
                self.download_items_map.pop(item_obj.item_id)
                self._save_downloads_to_local_history()
                self._refresh_display_order()
                self._set_status(f"Removed '{item_obj.video_title}' from list.", COLOR_STATUS_READY)

        if delete_file_from_disk:
            expected_ext = ".mp4" if item_obj.is_local_conversion else (".mp3" if item_obj.mp3_conversion else ".mp4")
            downloads_dir = os.path.join(os.getcwd(), self.settings['output_directory'])
            full_filepath = os.path.join(downloads_dir, item_obj.filename + expected_ext)
            if os.path.exists(full_filepath):
                try:
                    os.remove(full_filepath)
                    self._set_status(f"Removed '{item_obj.video_title}' and deleted file.", COLOR_STATUS_COMPLETE)
                except Exception as e:
                    messagebox.showerror("File Deletion Error", f"Could not delete file '{item_obj.filename}': {e}")
                    self._set_status(f"Failed to delete file for '{item_obj.video_title}'.", COLOR_STATUS_FAILED)
            else:
                self._set_status(f"File for '{item_obj.video_title}' not found for deletion.", COLOR_STATUS_READY)

    def _clear_queue(self):
        """Clears all items from the active and queued downloads."""
        for item in self.active_downloads[:]: item.abort_download()
        self.queued_downloads.clear();
        self.active_downloads.clear()
        ids_to_remove = [item.item_id for item in self.download_items_map.values() if item.is_active_item]
        for item_id in ids_to_remove: self.download_items_map.pop(item_id, None)
        self._refresh_display_order();
        self._set_status("Task queue cleared.", COLOR_STATUS_READY)
        messagebox.showinfo("Queue Cleared", "All pending tasks have been cleared.")

    def _clear_finished_history(self):
        """Clears all items from the finished tasks history."""
        if messagebox.askyesno("Clear History",
                               "Are you sure you want to clear all task history? This will not delete the actual converted/downloaded files."):
            ids_to_remove = [item.item_id for item in self.download_items_map.values() if not item.is_active_item]
            for item_id in ids_to_remove: self.download_items_map.pop(item_id, None)
            self._save_downloads_to_local_history();
            self._refresh_display_order();
            self._set_status("Task history cleared.", COLOR_STATUS_READY)

    def _refresh_display_order(self):
        """Destroys and recreates all download item frames to ensure correct order and visibility (active vs. history)."""
        self.downloads_canvas.update_idletasks();
        self.downloads_frame_inner.update_idletasks()
        for widget in self.downloads_frame_inner.winfo_children(): widget.destroy()

        header_frame = tk.Frame(self.downloads_frame_inner, bg="#e0e0e0");
        header_frame.pack(fill="x", padx=5, pady=(0, 2))
        columns = [("Name", 0), ("Status", 1), ("Date Added", 2), ("Date Completed", 3), ("Time / ETA", 4),
                   ("Action", 5)]
        header_frame.columnconfigure(0, weight=4);
        header_frame.columnconfigure(1, weight=2);
        header_frame.columnconfigure(2, weight=1)
        header_frame.columnconfigure(3, weight=1);
        header_frame.columnconfigure(4, weight=1);
        header_frame.columnconfigure(5, weight=1)
        header_frame.columnconfigure(6, weight=1)  # Added for new 'Remove' column

        for col_name, col_idx in columns:
            lbl = tk.Label(header_frame, text=col_name, font=BOLD_FONT, bg="#e0e0e0", borderwidth=1, relief="ridge")
            lbl.grid(row=0, column=col_idx, sticky="ew", padx=1, pady=0);
            lbl.bind("<Button-1>", lambda e, idx=col_idx: self._on_header_click(idx))

        sort_col = getattr(self, '_current_sort_col', 2);
        sort_reverse = getattr(self, '_current_sort_reverse', True)
        all_display_items = list(self.download_items_map.values())

        def sort_key(item):
            if sort_col == 0:
                return (item.video_title or item.filename or "").lower()
            elif sort_col == 1:
                return item.status.lower()
            elif sort_col == 2:
                try:
                    return time.mktime(time.strptime(item.date_added, "%m/%d/%y"))
                except Exception:
                    return 0
            elif sort_col == 3:
                try:
                    return time.mktime(time.strptime(item.date_completed, "%m/%d/%y"))
                except Exception:
                    return 0
            elif sort_col == 4:
                return item.elapsed_time_seconds
            else:
                return 0

        all_display_items.sort(key=sort_key, reverse=sort_reverse)

        for item_obj in all_display_items:
            item_obj.parent_frame = self.downloads_frame_inner;
            item_obj._build_frame_widgets()
            item_obj.frame.pack(fill="x", padx=5, pady=3);
            item_obj._update_title_label()
            item_obj.update_status(item_obj.status, item_obj._get_status_color(item_obj.status))
        self.downloads_frame_inner.update_idletasks();
        self.downloads_canvas.configure(scrollregion=self.downloads_canvas.bbox("all"))

    def _on_header_click(self, col_idx):
        """Handles sorting when a header is clicked."""
        prev_col = getattr(self, '_current_sort_col', 2);
        prev_rev = getattr(self, '_current_sort_reverse', True)
        if prev_col == col_idx:
            self._current_sort_reverse = not prev_rev
        else:
            self._current_sort_col = col_idx;
            self._current_sort_reverse = True if col_idx in [2, 3] else False
        self._refresh_display_order()

    def _get_item_data_for_history(self, item_obj):
        """Prepares a dictionary of item data for saving to history."""
        return {
            'id': item_obj.item_id, 'source_path': item_obj.source_path, 'quality': item_obj.quality,
            'filename': item_obj.filename, 'mp3_conversion': item_obj.mp3_conversion, 'source': item_obj.source,
            'referer': item_obj.referer, 'video_title': item_obj.video_title, 'status': item_obj.status,
            'date_added': item_obj.date_added, 'date_completed': item_obj.date_completed,
            'filename_provided_by_user': item_obj.filename_provided_by_user,
            'elapsed_time_seconds': item_obj.elapsed_time_seconds
        }

    def _save_downloads_to_local_history(self):
        """Saves the current finished tasks data (from map) to a local JSON file."""
        history_to_save = [self._get_item_data_for_history(item) for item in self.download_items_map.values() if
                           not item.is_active_item]
        history_to_save.sort(key=lambda x: time.mktime(time.strptime(x['date_completed'], "%m/%d/%y")) if x[
                                                                                                              'date_completed'] != 'N/A' else time.time(),
                             reverse=True)
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history_to_save, f, indent=4)
        except IOError as e:
            print(f"Error saving history: {e}")

    def _load_downloads_from_local_history(self):
        """Loads task history from a local JSON file on startup."""
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    loaded_history_data = json.load(f)
                    self.download_item_counter = max(
                        [item['id'] for item in loaded_history_data]) + 1 if loaded_history_data else 0
                    for item_data in loaded_history_data:
                        # Handle old 'url' key if present
                        if 'source_path' not in item_data and 'url' in item_data:
                            item_data['source_path'] = item_data['url']
                            del item_data['url']
                        # Handle old 'YouTube' source name if present
                        if item_data.get('source') == "YouTube":
                            item_data['source'] = DEFAULT_SOURCE

                        if item_data.get('date_added') and '|' in item_data['date_added']:
                            try:
                                dt_obj = time.strptime(item_data['date_added'], "%m|%d|%Y - %I:%M%p");
                                item_data[
                                    'date_added'] = time.strftime("%m/%d/%y", dt_obj)
                            except ValueError:
                                pass
                        if item_data.get('date_completed') and '|' in item_data['date_completed']:
                            try:
                                dt_obj = time.strptime(item_data['date_completed'], "%m|%d|%Y - %I:%M%p");
                                item_data[
                                    'date_completed'] = time.strftime("%m/%d/%y", dt_obj)
                            except ValueError:
                                pass
                        history_item = DownloadItem(self, item_data, is_active_item=False)
                        self.download_items_map[item_data['id']] = history_item
                self._refresh_display_order()
            except (IOError, json.JSONDecodeError) as e:
                print(f"Error loading history: {e}")
                messagebox.showwarning("History Load Error",
                                       f"Could not load download history. It might be corrupted or missing: {e}")
        else:
            self.download_item_counter = 0

    def _cleanup_temp_directories_on_launch(self):
        """Cleans up any lingering temporary download directories from previous sessions upon application launch."""
        # Use output_directory from settings to find the temp folder
        downloads_base_path = os.path.join(os.getcwd(), self.settings['output_directory'])
        full_temp_dir_path = os.path.join(downloads_base_path, TEMP_SUBDIR)

        if os.path.exists(full_temp_dir_path):
            print(f"Checking for lingering temporary directories in: {full_temp_dir_path}")
            for entry in os.listdir(full_temp_dir_path):
                entry_path = os.path.join(full_temp_dir_path, entry)
                if os.path.isdir(entry_path):
                    try:
                        print(f"Deleting lingering temporary directory: {entry_path}");
                        shutil.rmtree(entry_path)
                    except Exception as e:
                        print(f"Error deleting lingering temporary directory {entry_path}: {e}")
        else:
            print(f"Temporary directory not found: {full_temp_dir_path}. No cleanup needed.")


# Ensure main() is defined AFTER the class YTDLPGUIApp
def main():
    root = tk.Tk()
    app = YTDLPGUIApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
