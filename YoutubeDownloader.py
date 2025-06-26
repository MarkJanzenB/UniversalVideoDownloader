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

# --- Constants for consistent naming and values --
DOWNLOADS_DIR = "downloads"
TEMP_SUBDIR = "temp"
YOUTUBE_SOURCE = "YouTube"
XTREAM_SOURCE = "XtremeStream"
LOCAL_SOURCE = "Local" # New constant for local video conversion
MAX_CONCURRENT_DOWNLOADS = 2
HISTORY_FILE = "download_history.json"

# Colors for buttons/status
COLOR_ADD_BUTTON = "#28A745"  # Green
COLOR_ABORT_BUTTON = "#DC3545"  # Red
COLOR_CLEAR_BUTTON = "#FFC107"  # Yellow-Orange
COLOR_OPEN_FOLDER_BUTTON = "#6C754C"  # Dark Grey/Greenish Grey
COLOR_OPEN_FILE_BUTTON = "#17A2B8"  # Info Blue/Cyan
COLOR_BROWSE_FILE_BUTTON = "#007BFF" # Blue for browse

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
        # Handle backward compatibility: check for 'source_path', otherwise use 'url'
        self.source_path = item_data.get('source_path', item_data.get('url')) # Fallback from 'url'
        self.quality = item_data.get('quality', 'N/A')

        raw_filename = item_data.get('filename')
        self.filename = str(raw_filename) if raw_filename is not None else ''

        self.mp3_conversion = item_data.get('mp3_conversion', False)
        self.source = item_data.get('source', 'N/A')
        self.referer = item_data.get('referer', '')
        self.video_title = item_data.get('video_title', 'Fetching Title...')
        self.status = item_data.get('status', 'queued')
        self.date_added = item_data.get('date_added', 'N/A')
        self.date_completed = item_data.get('date_completed', 'N/A')
        self.filename_provided_by_user = item_data.get('filename_provided_by_user', False)
        self.elapsed_time_seconds = item_data.get('elapsed_time_seconds', 0)

        # New flag: Is this a local video conversion?
        self.is_local_conversion = (self.source == LOCAL_SOURCE)

        # If it's a local conversion, the title is simply the filename, and it's immediately ready
        if self.is_local_conversion:
            self.video_title = os.path.basename(self.source_path)
            self.filename = os.path.splitext(os.path.basename(self.source_path))[0] # Set filename to base name without extension
            self.is_title_fetched = True
            self.ready_for_download = True
            self.expected_final_ext = ".mp4" # Local conversions are always MP4 as per request
        else:
            self.is_title_fetched = self.filename_provided_by_user or (self.video_title != 'Fetching Title...')
            self.ready_for_download = not (is_active_item and not self.filename_provided_by_user and not self.is_title_fetched)
            self.expected_final_ext = ".mp3" if self.mp3_conversion else ".mp4"


        self.process = None
        self.output_queue = queue.Queue()
        self.start_time = None
        self.last_update_time = None
        self.is_aborted = False
        self.is_merging = False # Used for yt-dlp's merging phase
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
        self.frame.columnconfigure(0, weight=4)  # Name
        self.frame.columnconfigure(1, weight=2)  # Status/Progress
        self.frame.columnconfigure(2, weight=1)  # Date Added
        self.frame.columnconfigure(3, weight=1)  # Date Completed
        self.frame.columnconfigure(4, weight=1)  # Time/ETA
        self.frame.columnconfigure(5, weight=1)  # Action

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

        self.elapsed_time_label = tk.Label(self.frame, text="", font=SMALL_FONT, anchor="w", bg="#f0f0f0",
                                           width=8)
        self.elapsed_time_label.grid(row=0, column=4, sticky="w", padx=2, pady=0)

        self.abort_button = tk.Button(self.frame, text="Abort", command=self.abort_download, bg=COLOR_ABORT_BUTTON,
                                      fg="white", font=SMALL_FONT, width=8)
        self.open_file_button = tk.Button(self.frame, text="Open File", command=self._open_file_location,
                                          bg=COLOR_OPEN_FILE_BUTTON, fg="white", font=SMALL_FONT, width=10)
        self.retry_button = tk.Button(self.frame, text="Retry", command=self.retry_download, bg=COLOR_ADD_BUTTON,
                                      fg="white", font=SMALL_FONT, width=10)

        if self.is_active_item:
            self.abort_button.grid(row=0, column=5, sticky="e", padx=2, pady=0)
        else:
            if self.status in ['failed', 'aborted', 'cancelled']:
                self.retry_button.grid(row=0, column=5, sticky="e", padx=2, pady=0)
            elif self.status == 'completed':
                self.open_file_button.grid(row=0, column=5, sticky="e", padx=2, pady=0)

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
        """
        Formats total seconds into HH:MM:SS.
        """
        if total_seconds < 0:
            total_seconds = 0

        hours = int(total_seconds // 3600)
        remaining_seconds = total_seconds % 3600
        minutes = int(remaining_seconds // 60)
        seconds = int(remaining_seconds % 60)

        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def fetch_title_async(self):
        """Fetches the video title asynchronously and updates the label. Only for YouTube/XtremeStream."""
        if self.is_local_conversion:
            # No title fetching needed for local files, it's just the filename
            self.is_title_fetched = True
            self.ready_for_download = True
            self.app_instance.master.after(0, self.app_instance._refresh_display_order)
            return

        def _fetch():
            try:
                command = [
                    self.app_instance.yt_dlp_path,
                    "--print-json",
                    "--skip-download",
                    self.source_path
                ]
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
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"FileNotFoundError: yt-dlp.exe not found or not in PATH for URL: {self.source_path}")
            except subprocess.CalledProcessError as e:
                self.video_title = f"Error fetching title: Command failed. {e.stderr.strip()}"
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"subprocess.CalledProcessError for URL {self.source_path}: {e.stderr.strip()}")
            except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
                self.video_title = f"Error fetching title: {e}"
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"Decoding/Timeout Error for URL {self.source_path}: {e}")
            except Exception as e:
                self.video_title = f"Unexpected error fetching title: {e}"
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"General Error fetching title for URL {self.source_path}: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_title_label(self):
        """
        Updates the title label on the UI with fetched info,
        and sets wraplength dynamically based on column width,
        with explicit clipping if still too long.
        """
        self.frame.update_idletasks()

        total_frame_width = self.app_instance.downloads_canvas.winfo_width()
        if total_frame_width == 0:
            total_frame_width = 900

        name_col_ratio = 4 / 10
        safety_margin_px = 30
        name_column_pixel_width = int(total_frame_width * name_col_ratio) - safety_margin_px
        name_column_pixel_width = max(10, name_column_pixel_width)

        self.title_label.config(wraplength=name_column_pixel_width)

        if "Error" in self.video_title or self.status in ['failed', 'aborted', 'cancelled']:
            display_name_raw = f"{self.status.capitalize()}: {self.video_title}"
        elif self.is_local_conversion:
            # For local, video_title is already basename; use it directly
            display_name_raw = self.video_title
        else:
            display_name_raw = self.video_title if self.video_title and self.video_title != 'Fetching Title...' else (
                os.path.basename(self.filename) if self.filename else f"VideoPlayback_{self.item_id}")

        display_name_full = f"{display_name_raw} ({self.source})"

        font_obj = tkinter.font.Font(family=MAIN_FONT[0], size=MAIN_FONT[1])
        text_width_px = font_obj.measure(display_name_full)

        if text_width_px > name_column_pixel_width:
            truncated_text = ""
            for i in range(len(display_name_full)):
                test_text = display_name_full[:i + 1] + "..."
                if font_obj.measure(test_text) > name_column_pixel_width:
                    truncated_text = display_name_full[:i] + "..."
                    break
            if not truncated_text:
                truncated_text = display_name_full
            display_name_final = truncated_text
        else:
            display_name_final = display_name_full

        if self.title_label.winfo_exists():
            self.title_label.config(text=display_name_final)

        if self.date_added_label.winfo_exists():
            self.date_added_label.config(text=self.date_added)
        if self.date_completed_label.winfo_exists():
            self.date_completed_label.config(text=self.date_completed)
        if self.elapsed_time_label.winfo_exists():
            self.elapsed_time_label.config(
                text=self._format_seconds_to_dd_hh_mm_ss(self.elapsed_time_seconds))

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
        # Determine if it's an ffmpeg process based on source type
        is_ffmpeg_process = (self.source == LOCAL_SOURCE)
        threading.Thread(target=self._run_conversion_process, args=(command, is_ffmpeg_process,), daemon=True).start()

    def _build_command(self):
        """Builds the yt-dlp or ffmpeg command for this specific item."""
        downloads_dir = os.path.join(os.getcwd(), DOWNLOADS_DIR)
        temp_dir = os.path.join(downloads_dir, TEMP_SUBDIR, str(self.item_id))
        os.makedirs(temp_dir, exist_ok=True)
        out_name = self.filename

        if self.is_local_conversion:
            command = ["ffmpeg", "-i", self.source_path] # Input local file
            if self.quality == "Same as source":
                # Attempt to copy video/audio streams if compatible, otherwise re-encode with very high quality
                command += ["-c:v", "copy", "-c:a", "copy", "-map", "0", "-y", os.path.join(temp_dir, out_name + ".mp4")]
                # Note: 'copy' might fail if codecs are not natively supported by MP4 container.
                # A more robust "same as source" would involve probing the source for codec and
                # only using '-c:v copy -c:a copy' if compatible, otherwise re-encoding with a lossless/high-quality preset.
                # For simplicity here, we assume direct copy if possible. If copy fails, FFmpeg might
                # silently re-encode or throw an error depending on version/config.
            else:
                crf_value = 23 # Default medium quality
                if self.quality == "High Quality MP4":
                    crf_value = 18 # Lower CRF = higher quality (visually lossless for most)
                elif self.quality == "Low Quality MP4":
                    crf_value = 28 # Higher CRF = lower quality

                command += [
                    "-preset", "medium", # Conversion speed vs. compression efficiency
                    "-crf", str(crf_value), # Constant Rate Factor for video quality
                    "-c:v", "libx264", # Video codec
                    "-c:a", "aac", # Audio codec
                    "-b:a", "128k", # Audio bitrate
                    "-y", # Overwrite output files without asking
                    os.path.join(temp_dir, out_name + ".mp4") # Output to temp dir
                ]
            self.expected_final_ext = ".mp4"
            print(f"FFmpeg Command: {' '.join(command)}")
        else:
            # yt-dlp command for YouTube/XtremeStream
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

            if self.source == YOUTUBE_SOURCE:
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

            command += ["--paths", f"temp:{temp_dir}"]
            command += ["--newline"]
            print(f"Yt-dlp Command: {' '.join(command)}")
        return command

    def _run_conversion_process(self, command, is_ffmpeg_process):
        """Runs the subprocess (yt-dlp or ffmpeg) and captures its output."""
        rc = -1
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            self.process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                universal_newlines=True, creationflags=creationflags
            )
            for line in self.process.stdout:
                if self.is_aborted:
                    break
                self.output_queue.put(line)
                if self.app_instance.log_window_visible and self.app_instance.log_text:
                    self.app_instance.master.after(0, lambda l=line: self._append_to_log(l))

                if is_ffmpeg_process:
                    self._parse_ffmpeg_output_for_progress(line)
                else:
                    self._parse_output_for_progress(line) # For yt-dlp

                if self.start_time:
                    elapsed = time.time() - self.start_time
                    if self.elapsed_time_label.winfo_exists() and self.elapsed_time_label.winfo_ismapped():
                        self.app_instance.master.after(0, lambda e=elapsed: self.elapsed_time_label.config(
                            text=self._format_seconds_to_dd_hh_mm_ss(e)))

            rc = self.process.wait()
            if self.is_merging:
                if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
                    self.progress_bar.stop()

            if self.is_aborted:
                final_status = "aborted"
                self.update_status("aborted", COLOR_STATUS_ABORTED)
            elif rc == 0:
                final_status = "completed"
                self.update_status("completed", COLOR_STATUS_COMPLETE)
                if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
                    self.progress_bar.config(value=100, mode="determinate")

                temp_dir = os.path.join(os.getcwd(), DOWNLOADS_DIR, TEMP_SUBDIR, str(self.item_id))
                final_file_in_temp = os.path.join(temp_dir, self.filename + self.expected_final_ext)
                final_destination = os.path.join(os.getcwd(), DOWNLOADS_DIR, self.filename + self.expected_final_ext)

                if os.path.exists(final_file_in_temp):
                    try:
                        os.makedirs(os.path.join(os.getcwd(), DOWNLOADS_DIR), exist_ok=True)
                        shutil.move(final_file_in_temp, final_destination)
                        print(f"Moved final file from '{final_file_in_temp}' to '{final_destination}'")
                    except Exception as move_error:
                        print(f"Error moving final file: {move_error}")
                        self.app_instance.master.after(0, lambda: messagebox.showwarning(
                            "File Move Warning",
                            f"Conversion completed but could not move final file to downloads folder:\n{move_error}\n"
                            f"File might be in temporary folder: {final_file_in_temp}"
                        ))
                else:
                    print(f"Final file not found in temp directory: {final_file_in_temp}")
                    self.app_instance.master.after(0, lambda: messagebox.showwarning(
                        "File Not Found",
                        f"Final converted file was not found where expected in temp folder: {final_file_in_temp}"
                    ))

            else:
                final_status = "failed"
                self.update_status("failed", COLOR_STATUS_FAILED)

        except FileNotFoundError:
            final_status = "failed"
            self.update_status("failed", COLOR_STATUS_FAILED)
            tool_name = "ffmpeg.exe" if is_ffmpeg_process else "yt-dlp.exe"
            if self.app_instance.log_window_visible and self.app_instance.log_text:
                self.app_instance.master.after(0, lambda: self._append_to_log(
                    f"ERROR: {tool_name} not found or not in PATH.\n"))
            print(f"FileNotFoundError: {tool_name} not found or not in PATH for {self.source_path}")
        except Exception as e:
            final_status = "failed"
            self.update_status("failed", COLOR_STATUS_FAILED)
            if self.app_instance.log_window_visible and self.app_instance.log_text:
                self.app_instance.master.after(0, lambda: self._append_to_log(f"ERROR during execution: {e}\n"))
            print(f"Error during execution for {self.source_path}: {e}")
        finally:
            self.process = None
            if self.abort_button.winfo_exists():
                self.abort_button.config(state="disabled")
            temp_path = os.path.join(os.getcwd(), DOWNLOADS_DIR, TEMP_SUBDIR, str(self.item_id))
            if os.path.exists(temp_path):
                shutil.rmtree(temp_path, ignore_errors=True)

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
                    if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
                        self.progress_bar.stop()
                        self.progress_bar.config(mode="determinate")
                    self.is_merging = False

                if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
                    self.progress_bar.config(value=percent)

                speed_match = re.search(r'at\s+([0-9\.]+[KMG]?iB/s|\S+)(?:\s+ETA\s+(\d{2}:\d{2}))?', line)
                speed = speed_match.group(1) if speed_match and speed_match.group(1) else 'N/A'
                eta = speed_match.group(2) if speed_match and speed_match.group(2) else 'N/A'

                self.update_status(f"{percent:.1f}% ({speed}, ETA {eta})", COLOR_STATUS_PROGRESS)
            return

        if "merging formats" in line.lower() or "ffmpeg" in line.lower() or "postprocessing" in line.lower() or "extractaudio" in line.lower():
            if not self.is_merging:
                self.update_status("Converting/Merging...", COLOR_STATUS_PROGRESS)
                if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
                    self.progress_bar.config(mode="indeterminate")
                    self.progress_bar.start()
                self.is_merging = True
            return

        if "downloading" in line.lower() and not self.is_merging:
            self.update_status("Downloading...", COLOR_STATUS_PROGRESS)
            return

    def _parse_ffmpeg_output_for_progress(self, line):
        """Parses a line of FFmpeg output for progress."""
        # Example FFmpeg output: frame= 1500 fps= 100 q=28.0 size=   12345kB time=00:00:10.00 bitrate=1000.0kbits/s speed=2.5x
        time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
        speed_match = re.search(r'speed=\s*([0-9\.]+)x', line)

        if time_match:
            hours = int(time_match.group(1))
            minutes = int(time_match.group(2))
            seconds = int(time_match.group(3))
            current_time_seconds = hours * 3600 + minutes * 60 + seconds

            speed_str = f"{speed_match.group(1)}x" if speed_match else "N/A"
            self.update_status(f"Converting... ({self._format_seconds_to_dd_hh_mm_ss(current_time_seconds)}, Speed: {speed_str})", COLOR_STATUS_PROGRESS)
            if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists() and self.progress_bar['mode'] != "indeterminate":
                 self.progress_bar.config(mode="indeterminate")
                 self.progress_bar.start()
            self.is_merging = True
        elif "video:" in line or "audio:" in line and "global headers" in line:
            self.update_status("Converting...", COLOR_STATUS_PROGRESS)
            if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists() and self.progress_bar['mode'] != "indeterminate":
                self.progress_bar.config(mode="indeterminate")
                self.progress_bar.start()
            self.is_merging = True

    def update_status(self, text, color):
        """Updates the status label for this download item."""
        if self.status_label.winfo_exists():
            self.status_label.config(text=text.capitalize(), fg=color)
        self.status = text

    def abort_download(self):
        """Aborts the currently running download process."""
        self.is_aborted = True
        if self.process:
            try:
                self.process.kill()
                self.update_status("aborted", COLOR_STATUS_ABORTED)
                if self.is_merging:
                    if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
                        self.progress_bar.stop()
                        self.progress_bar.config(mode="determinate")
            except Exception:
                self.update_status("failed", COLOR_STATUS_FAILED)
        else:
            self.update_status("aborted", COLOR_STATUS_ABORTED)
            self.app_instance.remove_from_queue(self)

    def retry_download(self):
        """Resets the item and re-add it to the queue for retry."""
        self.status = "queued"
        self.date_completed = 'N/A'
        self.elapsed_time_seconds = 0
        self.start_time = None
        self.is_aborted = False
        self.is_merging = False
        self.is_active_item = True
        self.ready_for_download = True

        self.app_instance.queued_downloads.insert(0, self)
        self.app_instance._refresh_display_order()
        self.app_instance._set_status(f"Retrying download for '{self.video_title}'.", COLOR_STATUS_READY)

    def _open_file_location(self):
        """Opens the folder containing the downloaded file and highlights the file."""
        # Determine the expected file extension based on mp3_conversion OR if it was a local conversion (always mp4)
        if self.is_local_conversion:
            expected_ext = ".mp4"
        else:
            expected_ext = ".mp3" if self.mp3_conversion else ".mp4"

        full_filepath = os.path.join(os.getcwd(), DOWNLOADS_DIR, self.filename + expected_ext)

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


class YTDLPGUIApp:
    def __init__(self, master):
        self.master = master
        self._setup_window(master)

        self._configure_yt_dlp_path() # Still needed for YouTube/XtremeStream
        # FFmpeg path is assumed to be in system PATH for now
        self._create_menus()

        self._create_widgets()
        self._initialize_download_management()
        self._cleanup_temp_directories_on_launch()
        self._load_downloads_from_local_history()

        self.master.after(100, self._process_queue_loop)
        # Initialize UI state based on default source (YouTube)
        self.on_source_change(YOUTUBE_SOURCE)
        self.master.after_idle(self._refresh_display_order)

        self.log_window = None
        self.log_text = None
        self.log_window_visible = False

        # New instance variable for selected local file path
        self.selected_local_filepath = None

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

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        self.log_toggle_var = tk.BooleanVar(value=False)
        view_menu.add_checkbutton(label="Show Process Log", variable=self.log_toggle_var,
                                  command=self._toggle_log_window)

    def _show_versions_info(self):
        """Displays yt-dlp and ffmpeg version information."""
        yt_dlp_version = "Not Found"
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
            if ffmpeg_version_lines:
                ffmpeg_version = ffmpeg_version_lines[0]
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

        messagebox.showinfo(
            "About Versions",
            f"yt-dlp Version: {yt_dlp_version}\n"
            f"FFmpeg Version: {ffmpeg_version}\n\n"
            "This application uses yt-dlp for downloading and FFmpeg for media processing."
        )

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
            if self.log_window and self.log_window.winfo_exists():
                self.log_window.withdraw()

    def _on_log_window_close(self):
        """Handles the log window close button, updating the toggle variable."""
        self.log_toggle_var.set(False)
        self.log_window_visible = False
        if self.log_window:
            self.log_window.withdraw()

    def _open_downloads_folder(self):
        """Opens the main downloads directory."""
        downloads_path = os.path.join(os.getcwd(), DOWNLOADS_DIR)
        if not os.path.exists(downloads_path):
            os.makedirs(downloads_path, exist_ok=True)

        try:
            os.startfile(downloads_path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open downloads folder: {e}")

    def _create_widgets(self):
        self.main_frame = tk.Frame(self.master, padx=10, pady=10)
        self.main_frame.pack(fill="both", expand=True)
        self.main_frame.grid_columnconfigure(1, weight=1)

        input_frame = tk.LabelFrame(self.main_frame, text="Add New Download/Conversion", font=MAIN_FONT, padx=10, pady=10)
        input_frame.pack(fill="x", pady=5)
        input_frame.grid_columnconfigure(1, weight=1)

        row_idx = 0
        tk.Label(input_frame, text="Source:", font=MAIN_FONT).grid(row=row_idx, column=0, sticky="w", padx=5, pady=2)
        self.source_var = tk.StringVar(value=YOUTUBE_SOURCE)
        self.source_menu = tk.OptionMenu(input_frame, self.source_var, YOUTUBE_SOURCE, XTREAM_SOURCE, LOCAL_SOURCE,
                                         command=self.on_source_change)
        self.source_menu.grid(row=row_idx, column=1, sticky="ew", padx=5, pady=2)

        row_idx += 1
        self.referer_label = tk.Label(input_frame, text="Referer URL:", font=MAIN_FONT)
        self.referer_entry = tk.Entry(input_frame, font=MAIN_FONT)

        row_idx += 1
        # Target URL widgets (YouTube/XtremeStream)
        self.url_label = tk.Label(input_frame, text="Target URL:", font=MAIN_FONT)
        self.url_entry = tk.Entry(input_frame, font=MAIN_FONT)

        # Local File Widgets (for Local Source)
        self.local_filepath_label = tk.Label(input_frame, text="No file selected", font=MAIN_FONT, anchor="w", wraplength=400)
        self.browse_file_button = tk.Button(input_frame, text="Browse Local File", command=self._browse_local_file,
                                            bg=COLOR_BROWSE_FILE_BUTTON, fg="white", font=SMALL_FONT, width=15)


        self.QUALITY_ROW_IDX = row_idx + 1 # Dynamic row index for quality options

        # YouTube/XtremeStream Quality
        self.quality_label = tk.Label(input_frame, text="Quality:", font=MAIN_FONT)
        self.quality_var = tk.StringVar(value="Auto (Best available)")
        self.quality_menu = tk.OptionMenu(input_frame, self.quality_var, "Auto (Best available)")

        # Local Quality
        self.local_quality_label = tk.Label(input_frame, text="Output Quality:", font=MAIN_FONT)
        self.local_quality_var = tk.StringVar(value="Medium Quality MP4")
        self.local_quality_menu = tk.OptionMenu(input_frame, self.local_quality_var,
                                                 "Same as source", # New option, re-added
                                                 "High Quality MP4", "Medium Quality MP4", "Low Quality MP4")


        row_idx = self.QUALITY_ROW_IDX + 1
        tk.Label(input_frame, text="Output Filename (optional):", font=MAIN_FONT).grid(row=row_idx, column=0,
                                                                                       sticky="w", padx=5, pady=2)
        self.filename_entry = tk.Entry(input_frame, font=MAIN_FONT)
        self.filename_entry.grid(row=row_idx, column=1, sticky="ew", padx=5, pady=2)

        row_idx += 1
        self.mp3_var = tk.BooleanVar()
        self.mp3_check = tk.Checkbutton(input_frame, text="Convert to MP3 (for online sources)", variable=self.mp3_var, font=MAIN_FONT)
        self.mp3_check.grid(row=row_idx, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        row_idx += 1
        self.add_to_queue_button = tk.Button(input_frame, text="Add to Queue", command=self._add_current_to_queue,
                                             bg=COLOR_ADD_BUTTON, fg="white", font=BOLD_FONT)
        self.add_to_queue_button.grid(row=row_idx, column=0, columnspan=2, sticky="ew", pady=10)

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
                                              command=self._clear_finished_history, bg=COLOR_CLEAR_BUTTON,
                                              fg="black", font=BOLD_FONT)
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
        """Adjusts UI based on selected source (YouTube, XtremeStream, or Local)."""
        # Hide all source-specific widgets first
        self.referer_label.grid_forget()
        self.referer_entry.grid_forget()
        self.url_label.grid_forget()
        self.url_entry.grid_forget()
        self.quality_label.grid_forget()
        self.quality_menu.grid_forget()
        self.local_filepath_label.grid_forget()
        self.browse_file_button.grid_forget()
        self.local_quality_label.grid_forget()
        self.local_quality_menu.grid_forget()
        self.mp3_check.grid_forget() # Hide MP3 checkbox, re-grid if applicable

        current_row_idx = self.source_menu.grid_info()["row"] + 1

        if value == YOUTUBE_SOURCE:
            self.url_label.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.url_entry.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            current_row_idx += 1
            self._update_quality_options_grouped(
                [("Auto (Best available)", "Auto (Best available)")],
                [],
                [],
                [],
                [("1080", "High Quality - 1080p")],
                [("720", "Medium Quality - 720p")],
                [("480", "Low Quality - 480p")]
            )
            self.quality_label.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.quality_menu.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            self.url_entry.bind("<Return>", self._add_to_queue_on_enter)
            self.url_entry.bind("<FocusOut>", self._on_url_focus_out)
            self.mp3_check.grid(row=current_row_idx + 1, column=0, columnspan=2, sticky="w", padx=5, pady=2)
            self.mp3_check.config(state="normal") # Enable MP3 option for YouTube

        elif value == XTREAM_SOURCE:
            self.referer_label.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.referer_entry.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            current_row_idx += 1
            self.url_label.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.url_entry.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            self.url_entry.bind("<Return>", self._add_to_queue_on_enter)
            self.url_entry.bind("<FocusOut>", self._on_url_focus_out) # Keep focus out for XtremeStream too
            self.mp3_check.grid(row=current_row_idx + 1, column=0, columnspan=2, sticky="w", padx=5, pady=2)
            self.mp3_check.config(state="normal") # Enable MP3 option for XtremeStream

        elif value == LOCAL_SOURCE:
            # Unbind previous URL-related events
            self.url_entry.unbind("<Return>")
            self.url_entry.unbind("<FocusOut>")

            self.local_filepath_label.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            self.browse_file_button.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            current_row_idx += 1
            self.local_quality_label.grid(row=current_row_idx, column=0, sticky="w", padx=5, pady=2)
            self.local_quality_menu.grid(row=current_row_idx, column=1, sticky="ew", padx=5, pady=2)
            # Disable MP3 conversion checkbox for local (always MP4)
            self.mp3_check.grid(row=current_row_idx + 1, column=0, columnspan=2, sticky="w", padx=5, pady=2)
            self.mp3_check.config(state="disabled")
            self.mp3_var.set(False) # Ensure it's unchecked for local conversions
            # Clear url and filename entries when switching to local
            self.url_entry.delete(0, END)
            self.filename_entry.delete(0, END)
            self.local_filepath_label.config(text="No file selected")
            self.selected_local_filepath = None # Reset selected file
            self.filename_entry.delete(0,END) # Clear filename suggestion


        # Adjust the "Add to Queue" button's position
        # Get the row of the mp3_check, or the last shown widget if mp3_check is hidden.
        # Ensure 'current_row_idx' correctly reflects the last used row for placing the button.
        final_input_row = max(
            self.filename_entry.grid_info()["row"] if self.filename_entry.winfo_ismapped() else -1,
            self.mp3_check.grid_info()["row"] if self.mp3_check.winfo_ismapped() else -1,
            self.quality_menu.grid_info()["row"] if self.quality_menu.winfo_ismapped() else -1,
            self.local_quality_menu.grid_info()["row"] if self.local_quality_menu.winfo_ismapped() else -1,
            self.url_entry.grid_info()["row"] if self.url_entry.winfo_ismapped() else -1,
            self.referer_entry.grid_info()["row"] if self.referer_entry.winfo_ismapped() else -1,
            self.browse_file_button.grid_info()["row"] if self.browse_file_button.winfo_ismapped() else -1
        )
        self.add_to_queue_button.grid(row=final_input_row + 1, column=0, columnspan=2, sticky="ew", pady=10)


    def _set_status(self, text, color="black"):
        """Updates the main status bar."""
        self.status_bar.config(text=text, fg=color)

    def _browse_local_file(self):
        """Opens a file dialog to select a local video file for conversion."""
        filepath = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[("Video files", "*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.webm"),
                       ("All files", "*.*")]
        )
        if filepath:
            self.selected_local_filepath = filepath
            # Update label to show selected path, truncate if too long
            display_path = filepath
            if len(display_path) > 50: # Arbitrary length for truncation
                display_path = "..." + display_path[-47:]
            self.local_filepath_label.config(text=display_path)

            # Suggest filename without extension
            self.filename_entry.delete(0, END)
            self.filename_entry.insert(0, os.path.splitext(os.path.basename(filepath))[0])
        else:
            self.selected_local_filepath = None
            self.local_filepath_label.config(text="No file selected")
            self.filename_entry.delete(0, END)


    def _add_current_to_queue(self):
        """Adds the current input values as a new download/conversion item to the queue."""
        source = self.source_var.get()
        item_data = {}
        source_path = ""
        quality = "N/A"
        filename_provided_by_user = bool(self.filename_entry.get().strip())
        filename_for_item_data = self.filename_entry.get().strip()
        mp3_conversion = False # Default

        if source == LOCAL_SOURCE:
            source_path = self.selected_local_filepath
            if not source_path or not os.path.exists(source_path):
                messagebox.showwarning("Input Error", "Please select a local video file.")
                return
            quality = self.local_quality_var.get()
            # For local conversion, force mp3_conversion to False (always MP4 output)
            mp3_conversion = False
            if not filename_for_item_data:
                filename_for_item_data = os.path.splitext(os.path.basename(source_path))[0] # Use base filename
            video_title = os.path.basename(source_path) # Title for display will be the filename

        else: # YouTube or XtremeStream
            source_path = self.url_entry.get().strip()
            if not source_path:
                messagebox.showwarning("Input Error", "Target URL is required.")
                return
            if not (source_path.startswith("http://") or source_path.startswith("https://")):
                messagebox.showwarning("Input Error", "Invalid URL. Must start with http:// or https://")
                return
            quality = self.quality_var.get()
            mp3_conversion = self.mp3_var.get()
            video_title = 'Fetching Title...' # Will be updated by fetch_title_async

        referer = self.referer_entry.get().strip() if source == XTREAM_SOURCE else ""

        self.download_item_counter += 1
        item_id = self.download_item_counter

        item_data = {
            'id': item_id,
            'source_path': source_path, # Generic field for URL or File Path
            'quality': quality,
            'filename': filename_for_item_data,
            'mp3_conversion': mp3_conversion,
            'source': source,
            'referer': referer,
            'video_title': video_title,
            'status': 'queued',
            'date_added': time.strftime("%m/%d/%y"),
            'filename_provided_by_user': filename_provided_by_user,
            'elapsed_time_seconds': 0
        }

        new_item = DownloadItem(self, item_data, is_active_item=True)
        self.queued_downloads.append(new_item)
        self.download_items_map[item_id] = new_item
        self.total_downloads_added += 1
        self._refresh_display_order()
        self._set_status(f"Added '{source_path}' to queue.", COLOR_STATUS_READY)

        # Clear input fields
        self.url_entry.delete(0, END)
        self.filename_entry.delete(0, END)
        self.mp3_var.set(False)
        self.referer_entry.delete(0, END)
        self.local_filepath_label.config(text="No file selected")
        self.selected_local_filepath = None
        self.url_entry.focus_set()
        self.alert_on_completion_for_session = True


    def _add_to_queue_on_enter(self, event=None):
        """Handles adding to queue when Enter is pressed in URL entry."""
        # Only process if current source is not Local
        if self.source_var.get() != LOCAL_SOURCE:
            self._add_current_to_queue()

    def _on_url_focus_out(self, event=None):
        """
        Attempts to pre-fill filename based on URL if not provided by user and source is YouTube/XtremeStream.
        """
        if self.source_var.get() == LOCAL_SOURCE:
            return # Do not pre-fill for local source

        url = self.url_entry.get().strip()
        if url and not self.filename_entry.get().strip():
            temp_item_data = {
                'id': -1,
                'source_path': url,
                'quality': self.quality_var.get(),
                'filename': '',
                'mp3_conversion': self.mp3_var.get(),
                'source': self.source_var.get(),
                'referer': self.referer_entry.get().strip(),
                'video_title': 'Fetching Title...',
                'status': 'temp_fetching',
                'date_added': 'N/A',
                'filename_provided_by_user': False,
                'elapsed_time_seconds': 0
            }
            temp_item = DownloadItem(self, temp_item_data, is_active_item=True)

            def _update_filename_after_fetch():
                if not self.filename_entry.get().strip():
                    if temp_item.is_title_fetched and temp_item.video_title not in ['Unknown Title', 'Fetching Title...']:
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
        menu = self.quality_menu["menu"]
        menu.delete(0, "end")

        def add_command(value):
            menu.add_command(label=value, command=tk._setit(self.quality_var, value))

        if auto:
            for text, val in auto:
                add_command(text)
            menu.add_separator()
        if combined_video_audio:
            menu.add_command(label="--- Combined Video + Audio ---", state="disabled")
            for res, text in combined_video_audio:
                add_command(f"{text} - {res}p")
            menu.add_separator()
        if combined_audio_only:
            menu.add_command(label="--- Combined Audio Only ---", state="disabled")
            for res, text in combined_audio_only:
                add_command(f"{text} - {res}p")
            menu.add_separator()
        if video_only:
            menu.add_command(label="--- Video Only ---", state="disabled")
            for res, text in video_only:
                add_command(f"{text}")
            menu.add_separator()
        if high_quality_video:
            menu.add_command(label="--- High Quality Video ---", state="disabled")
            for res, text in high_quality_video:
                add_command(f"{text}")
            menu.add_separator()
        if medium_quality_video:
            menu.add_command(label="--- Medium Quality Video ---", state="disabled")
            for res, text in medium_quality_video:
                add_command(f"{text}")
            menu.add_separator()
        if low_quality_video:
            menu.add_command(label="--- Low Quality Video ---", state="disabled")
            for res, text in low_quality_video:
                add_command(f"{text}")

        if self.quality_var.get() not in [item[0] for item in
                                          auto + combined_video_audio + combined_audio_only + video_only + high_quality_video + medium_quality_video + low_quality_video]:
            if auto:
                self.quality_var.set(auto[0][0])
            else:
                self.quality_var.set("Auto (Best available)")

    def _process_queue_loop(self):
        """Manages the download queue, starting new downloads as slots become free."""
        active_count = len(self.active_downloads)

        next_item_to_start = None
        for i, item in enumerate(self.queued_downloads):
            if item.ready_for_download:
                next_item_to_start = self.queued_downloads.pop(i)
                break

        if next_item_to_start and active_count < MAX_CONCURRENT_DOWNLOADS:
            self.active_downloads.append(next_item_to_start)
            self._set_status(f"Starting {next_item_to_start.source} for {next_item_to_start.video_title}...", COLOR_STATUS_PROGRESS)
            next_item_to_start.start_download()
            self.is_queue_processing_active = True
            self.all_downloads_completed.clear()
        elif not self.active_downloads and not self.queued_downloads and self.is_queue_processing_active:
            self.is_queue_processing_active = False
            self.all_downloads_completed.set()

            if self.alert_on_completion_for_session and self.total_downloads_added > 0:
                messagebox.showinfo("Tasks Complete",
                                    f"All {self.completed_downloads_count} tasks finished!")
                self.alert_on_completion_for_session = False
                self.completed_downloads_count = 0
                self.total_downloads_added = 0
            self._set_status("All tasks finished. Ready.", COLOR_STATUS_COMPLETE)
        self.master.after(1000, self._process_queue_loop)

    def download_finished(self, item, final_status):
        """Called by a DownloadItem when its process completes (success/fail/abort)."""
        if item in self.active_downloads:
            self.active_downloads.remove(item)

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

    def remove_from_queue(self, item_to_remove):
        """Removes a specified item from the queued_downloads list."""
        if item_to_remove in self.queued_downloads:
            self.queued_downloads.remove(item_to_remove)
            self.download_items_map.pop(item_to_remove.item_id, None)
            self._refresh_display_order()
            self._set_status(f"Removed '{item_to_remove.video_title}' from queue.", COLOR_STATUS_READY)

    def _clear_queue(self):
        """Clears all items from the active and queued downloads."""
        for item in self.active_downloads[:]:
            item.abort_download()
        self.queued_downloads.clear()
        self.active_downloads.clear()

        ids_to_remove = [item.item_id for item in self.download_items_map.values() if item.is_active_item]
        for item_id in ids_to_remove:
            self.download_items_map.pop(item_id, None)

        self._refresh_display_order()
        self._set_status("Task queue cleared.", COLOR_STATUS_READY)
        messagebox.showinfo("Queue Cleared", "All pending tasks have been cleared.")

    def _clear_finished_history(self):
        """Clears all items from the finished tasks history."""
        if messagebox.askyesno("Clear History", "Are you sure you want to clear all task history? "
                                                "This will not delete the actual converted/downloaded files."):
            ids_to_remove = [item.item_id for item in self.download_items_map.values() if not item.is_active_item]
            for item_id in ids_to_remove:
                self.download_items_map.pop(item_id, None)

            self._save_downloads_to_local_history()
            self._refresh_display_order()
            self._set_status("Task history cleared.", COLOR_STATUS_READY)

    def _refresh_display_order(self):
        """
        Destroys and recreates all download item frames to ensure correct order
        and visibility (active vs. history).
        """
        self.downloads_canvas.update_idletasks()
        self.downloads_frame_inner.update_idletasks()

        for widget in self.downloads_frame_inner.winfo_children():
            widget.destroy()

        header_frame = tk.Frame(self.downloads_frame_inner, bg="#e0e0e0")
        header_frame.pack(fill="x", padx=5, pady=(0, 2))
        columns = [
            ("Name", 0),
            ("Status", 1),
            ("Date Added", 2),
            ("Date Completed", 3),
            ("Time / ETA", 4),
            ("Action", 5)
        ]
        header_frame.columnconfigure(0, weight=4)
        header_frame.columnconfigure(1, weight=2)
        header_frame.columnconfigure(2, weight=1)
        header_frame.columnconfigure(3, weight=1)
        header_frame.columnconfigure(4, weight=1)
        header_frame.columnconfigure(5, weight=1)

        for col_name, col_idx in columns:
            lbl = tk.Label(header_frame, text=col_name, font=BOLD_FONT, bg="#e0e0e0", borderwidth=1, relief="ridge")
            lbl.grid(row=0, column=col_idx, sticky="ew", padx=1, pady=0)
            lbl.bind("<Button-1>", lambda e, idx=col_idx: self._on_header_click(idx))

        sort_col = getattr(self, '_current_sort_col', 2)
        sort_reverse = getattr(self, '_current_sort_reverse', True)
        all_display_items = list(self.download_items_map.values())

        def sort_key(item):
            if sort_col == 0:  # Name
                return (item.video_title or item.filename or "").lower()
            elif sort_col == 1:  # Status
                return item.status.lower()
            elif sort_col == 2:  # Date Added
                try:
                    return time.mktime(time.strptime(item.date_added, "%m/%d/%y"))
                except Exception:
                    return 0
            elif sort_col == 3:  # Date Completed
                try:
                    return time.mktime(time.strptime(item.date_completed, "%m/%d/%y"))
                except Exception:
                    return 0
            elif sort_col == 4:  # Time/ETA (elapsed time)
                return item.elapsed_time_seconds
            else:
                return 0

        all_display_items.sort(key=sort_key, reverse=sort_reverse)

        for item_obj in all_display_items:
            item_obj.parent_frame = self.downloads_frame_inner
            item_obj._build_frame_widgets()
            item_obj.frame.pack(fill="x", padx=5, pady=3)
            item_obj._update_title_label()
            item_obj.update_status(item_obj.status, item_obj._get_status_color(item_obj.status))

        self.downloads_frame_inner.update_idletasks()
        self.downloads_canvas.configure(scrollregion=self.downloads_canvas.bbox("all"))

    def _on_header_click(self, col_idx):
        """Handles sorting when a header is clicked."""
        prev_col = getattr(self, '_current_sort_col', 2)
        prev_rev = getattr(self, '_current_sort_reverse', True)
        if prev_col == col_idx:
            self._current_sort_reverse = not prev_rev
        else:
            self._current_sort_col = col_idx
            self._current_sort_reverse = True if col_idx in [2, 3] else False
        self._refresh_display_order()

    def _get_item_data_for_history(self, item_obj):
        """Prepares a dictionary of item data for saving to history."""
        return {
            'id': item_obj.item_id,
            'source_path': item_obj.source_path, # Now source_path
            'quality': item_obj.quality,
            'filename': item_obj.filename,
            'mp3_conversion': item_obj.mp3_conversion,
            'source': item_obj.source,
            'referer': item_obj.referer,
            'video_title': item_obj.video_title,
            'status': item_obj.status,
            'date_added': item_obj.date_added,
            'date_completed': item_obj.date_completed,
            'filename_provided_by_user': item_obj.filename_provided_by_user,
            'elapsed_time_seconds': item_obj.elapsed_time_seconds
        }

    def _save_downloads_to_local_history(self):
        """Saves the current finished tasks data (from map) to a local JSON file."""
        history_to_save = [
            self._get_item_data_for_history(item)
            for item in self.download_items_map.values()
            if not item.is_active_item
        ]
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

                    if loaded_history_data:
                        all_ids = [item['id'] for item in loaded_history_data]
                        if all_ids:
                            self.download_item_counter = max(all_ids) + 1
                        else:
                            self.download_item_counter = 0
                    else:
                        self.download_item_counter = 0

                    for item_data in loaded_history_data:
                        # Handle backward compatibility for 'url' field if 'source_path' is missing
                        if 'source_path' not in item_data and 'url' in item_data:
                            item_data['source_path'] = item_data['url']
                            del item_data['url'] # Clean up the old key if you want to standardize

                        # Before creating DownloadItem, parse date_added and date_completed to ensure
                        # they are in the expected "MM/DD/YY" format for consistency, especially if loading
                        # from an older history file format.
                        # Convert old "MM|DD|YYYY - H:MMpm" to "MM/DD/YY"
                        if item_data.get('date_added') and '|' in item_data['date_added']:
                            try:
                                dt_obj = time.strptime(item_data['date_added'], "%m|%d|%Y - %I:%M%p")
                                item_data['date_added'] = time.strftime("%m/%d/%y", dt_obj)
                            except ValueError:
                                pass  # Keep as is if parsing fails

                        if item_data.get('date_completed') and '|' in item_data['date_completed']:
                            try:
                                dt_obj = time.strptime(item_data['date_completed'], "%m|%d|%Y - %I:%M%p")
                                item_data['date_completed'] = time.strftime("%m/%d/%y", dt_obj)
                            except ValueError:
                                pass  # Keep as is if parsing fails

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
        """
        Cleans up any lingering temporary download directories from previous sessions
        upon application launch.
        """
        full_temp_dir_path = os.path.join(os.getcwd(), DOWNLOADS_DIR, TEMP_SUBDIR)
        if os.path.exists(full_temp_dir_path):
            print(f"Checking for lingering temporary directories in: {full_temp_dir_path}")
            for entry in os.listdir(full_temp_dir_path):
                entry_path = os.path.join(full_temp_dir_path, entry)
                if os.path.isdir(entry_path):
                    try:
                        print(f"Deleting lingering temporary directory: {entry_path}")
                        shutil.rmtree(entry_path)
                    except Exception as e:
                        print(f"Error deleting lingering temporary directory {entry_path}: {e}")
        else:
            print(f"Temporary directory not found: {full_temp_dir_path}. No cleanup needed.")


def main():
    root = tk.Tk()
    app = YTDLPGUIApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

