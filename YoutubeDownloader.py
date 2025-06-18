import tkinter as tk
from tkinter import scrolledtext, messagebox, END, ttk
import subprocess
import sys
import os
import threading
import queue
import shutil
import time
import re
import json  # For parsing local history JSON

# --- Constants for consistent naming and values --
DOWNLOADS_DIR = "downloads"
TEMP_SUBDIR = "temp"
YOUTUBE_SOURCE = "YouTube"
XTREAM_SOURCE = "XtremeStream"
MAX_CONCURRENT_DOWNLOADS = 2
HISTORY_FILE = "download_history.json"  # Local history file

# Colors for buttons/status (Tailwind-like or common vibrant colors)
COLOR_ADD_BUTTON = "#28A745"  # Green
COLOR_ABORT_BUTTON = "#DC3545"  # Red
COLOR_CLEAR_BUTTON = "#FFC107"  # Yellow-Orange
COLOR_OPEN_FOLDER_BUTTON = "#6C757D"  # Grey/Dark grey
COLOR_OPEN_FILE_BUTTON = "#17A2B8"  # Info Blue/Cyan

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
    Manages the UI and logic for a single download.
    Can represent an active/queued download or a finished history item.
    """

    def __init__(self, app_instance, item_data, is_active_item=True):
        self.parent_frame = None  # Will be set dynamically during _refresh_display_order
        self.app_instance = app_instance

        # Load data from item_data dictionary
        self.item_id = item_data.get('id')  # Unique ID for this item instance
        self.url = item_data['url']
        self.quality = item_data.get('quality', 'N/A')  # Quality might not be in history items

        # Ensure filename is always a string.
        # Get the raw value, then explicitly convert to string if not None, otherwise default to empty string.
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

        # Flag to indicate if the video title has been successfully fetched
        self.is_title_fetched = self.filename_provided_by_user or (self.video_title != 'Fetching Title...')

        # New flag: Is this item ready to be downloaded? (i.e., title fetched if needed)
        # If it's a history item or filename was user-provided, it's ready.
        # If it's a new active item that needs title fetching, it's not ready yet.
        self.ready_for_download = not (
                    is_active_item and not self.filename_provided_by_user and not self.is_title_fetched)

        self.process = None
        self.output_queue = queue.Queue()
        self.start_time = None
        self.last_update_time = None
        self.is_aborted = False
        self.is_merging = False
        self.is_active_item = is_active_item  # This flag determines active/history layout, not if it's currently running

        self.frame = None
        self.retry_button = None  # Initialize retry button attribute

        # For new active items, if filename isn't provided, fetch the title asynchronously
        if self.is_active_item and not self.filename_provided_by_user and not self.is_title_fetched:
            self.fetch_title_async()

    def _build_frame_widgets(self):
        """Builds or rebuilds the UI elements for this individual download item."""
        if self.frame and self.frame.winfo_exists():
            self.frame.destroy()

        self.frame = tk.Frame(self.parent_frame, bd=2, relief=tk.GROOVE, padx=5, pady=5, bg="#f0f0f0")
        # Column 0: Title/URL (expands)
        # Column 1: Progress (fixed)
        # Column 2: Date Added (fixed)
        # Column 3: Time Elapsed (fixed)
        # Column 4: Status (fixed) (for active items, this is for overall text updates from parse_output)
        # Column 5: Buttons (fixed)
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=0)
        self.frame.columnconfigure(2, weight=0)
        self.frame.columnconfigure(3, weight=0)
        self.frame.columnconfigure(4, weight=0)  # Status or Date Completed
        self.frame.columnconfigure(5, weight=0)  # Buttons

        # Adjusted wraplengths and widths for better fit in the wider window
        self.title_label = tk.Label(self.frame, text="", font=MAIN_FONT, anchor="w", bg="#f0f0f0", wraplength=400,
                                    # Increased wraplength for title
                                    justify="left")
        self.url_label = tk.Label(self.frame, text="", font=SMALL_FONT, anchor="w", bg="#f0f0f0", wraplength=500,
                                  # Increased wraplength for URL
                                  justify="left")
        self.status_label = tk.Label(self.frame, text="", font=SMALL_FONT, anchor="w", bg="#f0f0f0",
                                     fg=COLOR_STATUS_READY, width=15,
                                     wraplength=0)  # Fixed width for status, no wrapping

        # Increased width and explicitly set wraplength=0 to prevent wrapping
        self.date_added_label = tk.Label(self.frame, text=f"Added: {self.date_added}", font=SMALL_FONT, anchor="w",
                                         bg="#f0f0f0", width=12, wraplength=0)
        self.date_completed_label = tk.Label(self.frame, text=f"Completed: {self.date_completed}", font=SMALL_FONT,
                                             anchor="w", bg="#f0f0f0", width=12, wraplength=0)
        self.elapsed_time_label = tk.Label(self.frame, text="", font=SMALL_FONT, anchor="w", bg="#f0f0f0",
                                           width=9, wraplength=0)

        self.progress_bar = ttk.Progressbar(self.frame, orient="horizontal", mode="determinate",
                                            length=150)  # Slightly increased length
        self.abort_button = tk.Button(self.frame, text="Abort", command=self.abort_download, bg=COLOR_ABORT_BUTTON,
                                      fg="white", font=SMALL_FONT, width=10)  # Increased button width

        self.open_file_button = tk.Button(self.frame, text="Open File", command=self._open_file_location,
                                          bg=COLOR_OPEN_FILE_BUTTON, fg="white", font=SMALL_FONT,
                                          width=12)  # Increased button width
        self.retry_button = tk.Button(self.frame, text="Retry", command=self.retry_download,
                                      bg=COLOR_ADD_BUTTON, fg="white", font=SMALL_FONT,
                                      width=12)  # Increased button width

        if self.is_active_item:
            # Layout for active/queued items: title - progress bar - added - time elapsed - abort button
            # All on row 0, using new columns for better spacing
            self.title_label.grid(row=0, column=0, sticky="nw", padx=2, pady=0)
            self.progress_bar.grid(row=0, column=1, sticky="ew", padx=2, pady=0)
            self.date_added_label.grid(row=0, column=2, sticky="nw", padx=2, pady=0)
            self.elapsed_time_label.grid(row=0, column=3, sticky="nw", padx=2, pady=0)
            self.abort_button.grid(row=0, column=5, sticky="e", padx=2, pady=0)
            # Status text for active items will update the title label if needed, or primarily in log
            self.status_label.grid_forget()
            self.url_label.grid_forget()
            self.date_completed_label.grid_forget()
            self.open_file_button.grid_forget()
            self.retry_button.grid_forget()
        else:
            # Layout for finished/errored items:
            # Row 0: title (full width)
            # Row 1: URL (full width)
            # Row 2: Status - Added Date - Completed Date - Time Elapsed - (Open File / Retry)
            self.title_label.grid(row=0, column=0, columnspan=6, sticky="nw", padx=2, pady=0)  # Spanning all columns
            self.url_label.grid(row=1, column=0, columnspan=6, sticky="nw", padx=2, pady=0)  # Spanning all columns
            # Reduced padx for closer packing
            self.status_label.grid(row=2, column=0, sticky="w", padx=0, pady=0)
            self.date_added_label.grid(row=2, column=1, sticky="w", padx=0, pady=0)
            self.date_completed_label.grid(row=2, column=2, sticky="w", padx=0, pady=0)
            self.elapsed_time_label.grid(row=2, column=3, sticky="w", padx=0, pady=0)

            # Conditionally show Open File or Retry button
            if self.status in ['failed', 'aborted', 'cancelled']:
                self.retry_button.grid(row=2, column=5, sticky="e", padx=2, pady=0)  # Moved to last column
                self.open_file_button.grid_forget()
            elif self.status == 'completed':
                self.open_file_button.grid(row=2, column=5, sticky="e", padx=2, pady=0)  # Moved to last column
                self.retry_button.grid_forget()
            else:
                self.open_file_button.grid_forget()
                self.retry_button.grid_forget()

            self.progress_bar.grid_forget()
            self.abort_button.grid_forget()

            # Set progress bar for display only (not functional for history items)
            if self.status == 'completed':
                self.progress_bar.config(value=100, mode="determinate")
            else:
                self.progress_bar.config(value=0, mode="determinate")
            if hasattr(self, 'abort_button') and self.abort_button.winfo_exists():
                self.abort_button.config(state="disabled")

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
        """Fetches the video title asynchronously and updates the label."""

        def _fetch():
            try:
                command = [
                    self.app_instance.yt_dlp_path,
                    "--print-json",
                    "--skip-download",
                    self.url
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
                self.ready_for_download = True  # Mark as ready after title fetch
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)

            except FileNotFoundError:
                self.video_title = "Error: yt-dlp.exe not found."
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True  # Still mark as ready, with fallback filename
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"FileNotFoundError: yt-dlp.exe not found or not in PATH for URL: {self.url}")
            except subprocess.CalledProcessError as e:
                self.video_title = f"Error fetching title: Command failed. {e.stderr.strip()}"
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True  # Still mark as ready, with fallback filename
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"subprocess.CalledProcessError for URL {self.url}: {e.stderr.strip()}")
            except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
                self.video_title = f"Error fetching title: {e}"
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True  # Still mark as ready, with fallback filename
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"Decoding/Timeout Error for URL {self.url}: {e}")
            except Exception as e:
                self.video_title = f"Unexpected error fetching title: {e}"
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"
                self.is_title_fetched = False
                self.ready_for_download = True  # Still mark as ready, with fallback filename
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"General Error fetching title for URL {self.url}: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_title_label(self):
        """Updates the title label on the UI with the fetched title."""
        display_name = self.video_title if self.video_title and self.video_title != 'Fetching Title...' else (
            os.path.basename(self.filename) if self.filename else self.url)
        # Clip title for display if too long
        if len(display_name) > 60:  # Adjusted clipping length for better fit
            display_name = display_name[:57] + "..."

        if self.title_label.winfo_exists():
            self.title_label.config(text=f"{display_name} ({self.source})")
        if self.date_added_label.winfo_exists():
            # Ensure the "Added:" prefix is handled correctly without wrapping itself
            self.date_added_label.config(text=f"Added: {self.date_added}")

        if not self.is_active_item:
            display_url = self.url
            # Clip URL for display if too long
            if len(display_url) > 70:  # Adjusted clipping length for better fit
                display_url = display_url[:67] + "..."
            if self.url_label.winfo_exists():
                self.url_label.config(text=f"URL: {display_url}")
            if self.date_completed_label.winfo_exists():
                self.date_completed_label.config(text=f"Completed: {self.date_completed}")
            if self.elapsed_time_label.winfo_exists():
                self.elapsed_time_label.config(
                    text=f"Time: {self._format_seconds_to_dd_hh_mm_ss(self.elapsed_time_seconds)}")

    def start_download(self):
        """Starts the yt-dlp process for this item in a new thread."""
        self.is_aborted = False
        self.is_merging = False
        self.start_time = time.time()
        self.last_update_time = time.time()
        self.update_status("active", COLOR_STATUS_PROGRESS)
        self.is_active_item = True
        self.app_instance._refresh_display_order()

        if self.abort_button.winfo_exists():
            self.abort_button.config(state="normal")
        if self.progress_bar.winfo_exists():
            self.progress_bar.config(value=0)
            self.progress_bar.config(mode="determinate")

        if self.elapsed_time_label.winfo_exists():
            self.elapsed_time_label.config(text=f"Time: {self._format_seconds_to_dd_hh_mm_ss(0)}")

        command = self._build_command()
        threading.Thread(target=self._run_yt_dlp, args=(command,), daemon=True).start()

    def _build_command(self):
        """Builds the yt-dlp command for this specific download item."""
        command = [self.app_instance.yt_dlp_path, self.url]

        if self.source == XTREAM_SOURCE and self.referer:
            command += ["--add-header", f"referer: {self.referer}"]

        downloads_dir = os.path.join(os.getcwd(), DOWNLOADS_DIR)
        temp_dir = os.path.join(downloads_dir, TEMP_SUBDIR, str(self.item_id))
        os.makedirs(temp_dir, exist_ok=True)

        # All yt-dlp output will initially go into the temporary directory
        # The final file will be moved to the main downloads directory after completion
        out_name = self.filename
        if self.mp3_conversion:
            # Explicitly output as .mp3 inside the temp directory
            command += ["--extract-audio", "--audio-format", "mp3", "--output",
                        os.path.join(temp_dir, out_name + ".mp3")]
            self.expected_final_ext = ".mp3"
        else:
            # Explicitly output as .mp4 inside the temp directory
            command += ["--recode-video", "mp4", "--output", os.path.join(temp_dir, out_name + ".mp4")]
            self.expected_final_ext = ".mp4"

        if self.source == YOUTUBE_SOURCE:
            if "Auto (Best available)" in self.quality:
                command += ['-f', 'bestvideo+bestaudio/best']
            elif self.quality == "High Quality - 1080p":
                command += ['-f', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]']
            elif self.quality == "Medium Quality - 720p":
                command += ['-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]']
            elif "Combined" in self.quality:
                res = re.search(r'(\d+)p', self.quality).group(1)
                command += ['-f', f'bestvideo[height<={res}]+bestaudio/best[height<={res}]']
            elif "Video Only" in self.quality:
                res = re.search(r'(\d+)p', self.quality).group(1)
                command += ['-f', f'bestvideo[height<={res}]']

        # Add the temporary download path for yt-dlp's internal temp handling
        command += ["--paths", f"temp:{temp_dir}"]
        command += ["--newline"]
        return command

    def _run_yt_dlp(self, command):
        """Runs the yt-dlp subprocess and captures its output."""
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

                self._parse_output_for_progress(line)
                if self.start_time:
                    elapsed = time.time() - self.start_time
                    if self.elapsed_time_label.winfo_exists() and self.elapsed_time_label.winfo_ismapped():
                        self.app_instance.master.after(0, lambda e=elapsed: self.elapsed_time_label.config(
                            text=f"Time: {self._format_seconds_to_dd_hh_mm_ss(e)}"))

            rc = self.process.wait()
            if self.is_merging:
                if self.progress_bar.winfo_exists():
                    self.progress_bar.stop()

            if self.is_aborted:
                final_status = "aborted"
                self.update_status("aborted", COLOR_STATUS_ABORTED)
            elif rc == 0:
                final_status = "completed"
                self.update_status("completed", COLOR_STATUS_COMPLETE)
                if self.progress_bar.winfo_exists():
                    self.progress_bar.config(value=100, mode="determinate")

                # --- Move final file from temp to downloads directory ---
                temp_dir = os.path.join(os.getcwd(), DOWNLOADS_DIR, TEMP_SUBDIR, str(self.item_id))
                final_file_in_temp = os.path.join(temp_dir, self.filename + self.expected_final_ext)
                final_destination = os.path.join(os.getcwd(), DOWNLOADS_DIR, self.filename + self.expected_final_ext)

                if os.path.exists(final_file_in_temp):
                    try:
                        # Ensure the main downloads directory exists
                        os.makedirs(os.path.join(os.getcwd(), DOWNLOADS_DIR), exist_ok=True)
                        shutil.move(final_file_in_temp, final_destination)
                        print(f"Moved final file from '{final_file_in_temp}' to '{final_destination}'")
                    except Exception as move_error:
                        print(f"Error moving final file: {move_error}")
                        # If move fails, still mark as completed, but warn user
                        self.app_instance.master.after(0, lambda: messagebox.showwarning(
                            "File Move Warning",
                            f"Download completed but could not move final file to downloads folder:\n{move_error}\n"
                            f"File might be in temporary folder: {final_file_in_temp}"
                        ))
                else:
                    print(f"Final file not found in temp directory: {final_file_in_temp}")
                    self.app_instance.master.after(0, lambda: messagebox.showwarning(
                        "File Not Found",
                        f"Final downloaded file was not found where expected after conversion in temp folder: {final_file_in_temp}"
                    ))

            else:
                final_status = "failed"
                self.update_status("failed", COLOR_STATUS_FAILED)

        except FileNotFoundError:
            final_status = "failed"
            self.update_status("failed", COLOR_STATUS_FAILED)
            if self.app_instance.log_window_visible and self.app_instance.log_text:
                self.app_instance.master.after(0, lambda: self._append_to_log(
                    "ERROR: yt-dlp.exe not found or not in PATH.\n"))
            print(f"FileNotFoundError: yt-dlp.exe not found or not in PATH for URL: {self.url}")
        except Exception as e:
            final_status = "failed"
            self.update_status("failed", COLOR_STATUS_FAILED)
            if self.app_instance.log_window_visible and self.app_instance.log_text:
                self.app_instance.master.after(0, lambda: self._append_to_log(f"ERROR during yt-dlp execution: {e}\n"))
            print(f"Error during yt-dlp execution for URL {self.url}: {e}")
        finally:
            self.process = None
            if self.abort_button.winfo_exists():
                self.abort_button.config(state="disabled")
            temp_path = os.path.join(os.getcwd(), DOWNLOADS_DIR, TEMP_SUBDIR, str(self.item_id))
            if os.path.exists(temp_path):
                shutil.rmtree(temp_path, ignore_errors=True)  # Always clean up the temporary folder

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
                    if self.progress_bar.winfo_exists():
                        self.progress_bar.stop()
                        self.progress_bar.config(mode="determinate")
                    self.is_merging = False

                if self.progress_bar.winfo_exists():
                    self.progress_bar.config(value=percent)

                speed_match = re.search(r'at\s+([0-9\.]+[KMG]?iB/s|\S+)(?:\s+ETA\s+(\d{2}:\d{2}))?', line)
                speed = speed_match.group(1) if speed_match and speed_match.group(1) else 'N/A'
                eta = speed_match.group(2) if speed_match and speed_match.group(2) else 'N/A'

                self.update_status(f"Downloading... {percent:.1f}% ({speed}, ETA {eta})", COLOR_STATUS_PROGRESS)
            return

        if "merging formats" in line.lower() or "ffmpeg" in line.lower() or "postprocessing" in line.lower() or "extractaudio" in line.lower():
            if not self.is_merging:
                self.update_status("Converting/Merging...", COLOR_STATUS_PROGRESS)
                if self.progress_bar.winfo_exists():
                    self.progress_bar.config(mode="indeterminate")
                    self.progress_bar.start()
                self.is_merging = True
            return

        if "downloading" in line.lower() and not self.is_merging:
            self.update_status("Downloading...", COLOR_STATUS_PROGRESS)
            return

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
                    if self.progress_bar.winfo_exists():
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
        self.date_completed = 'N/A'  # Clear completion date
        self.elapsed_time_seconds = 0  # Reset elapsed time
        self.start_time = None  # Reset start time
        self.is_aborted = False  # Clear any previous abort state
        self.is_merging = False  # Clear any previous merging state
        self.is_active_item = True  # Mark as active again
        self.ready_for_download = True  # Assume ready for download after retry request (or could re-fetch title if needed)

        # Re-queue the item
        self.app_instance.queued_downloads.insert(0, self)  # Add to the front of the queue
        self.app_instance._refresh_display_order()  # Refresh display to move it back to active section
        self.app_instance._set_status(f"Retrying download for '{self.video_title}'.", COLOR_STATUS_READY)

    def _open_file_location(self):
        """Opens the folder containing the downloaded file and highlights the file."""
        # Determine the expected file extension based on mp3_conversion
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

        self._configure_yt_dlp_path()
        self._create_menus()

        self._create_widgets()
        self._initialize_download_management()
        self._cleanup_temp_directories_on_launch()
        self._load_downloads_from_local_history()

        self.master.after(100, self._process_queue_loop)
        self.on_source_change(YOUTUBE_SOURCE)

        self.log_window = None
        self.log_text = None
        self.log_window_visible = False

    def _setup_window(self, master):
        master.title("YouTube Downloader powered by yt-dlp")
        # Increased width to 1000 for better element spacing
        master.geometry("1000x650")
        # Set window to not be resizable
        master.resizable(False, False)
        master.minsize(1000, 650)  # Set minimum size to initial size
        master.maxsize(1000, 650)  # Set maximum size to initial size
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
        view_menu.add_checkbutton(label="Show yt-dlp Process Log", variable=self.log_toggle_var,
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
        """Toggles the visibility of the yt-dlp process log window."""
        self.log_window_visible = self.log_toggle_var.get()

        if self.log_window_visible:
            if not self.log_window or not self.log_window.winfo_exists():
                self.log_window = tk.Toplevel(self.master)
                self.log_window.title("yt-dlp Process Log")
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

        input_frame = tk.LabelFrame(self.main_frame, text="Add New Download", font=MAIN_FONT, padx=10, pady=10)
        input_frame.pack(fill="x", pady=5)
        input_frame.grid_columnconfigure(1, weight=1)

        row_idx = 0
        tk.Label(input_frame, text="Source:", font=MAIN_FONT).grid(row=row_idx, column=0, sticky="w", padx=5, pady=2)
        self.source_var = tk.StringVar(value=YOUTUBE_SOURCE)
        self.source_menu = tk.OptionMenu(input_frame, self.source_var, YOUTUBE_SOURCE, XTREAM_SOURCE,
                                         command=self.on_source_change)
        self.source_menu.grid(row=row_idx, column=1, sticky="ew", padx=5, pady=2)

        row_idx += 1
        self.referer_label = tk.Label(input_frame, text="Referer URL:", font=MAIN_FONT)
        self.referer_entry = tk.Entry(input_frame, font=MAIN_FONT)

        row_idx += 1
        tk.Label(input_frame, text="Target URL:", font=MAIN_FONT).grid(row=row_idx, column=0, sticky="w", padx=5,
                                                                       pady=2)
        self.url_entry = tk.Entry(input_frame, font=MAIN_FONT)
        self.url_entry.grid(row=row_idx, column=1, sticky="ew", padx=5, pady=2)
        self.url_entry.bind("<Return>", self._add_to_queue_on_enter)
        self.url_entry.bind("<FocusOut>", self._on_url_focus_out)

        self.QUALITY_ROW_IDX = row_idx + 1
        self.quality_label = tk.Label(input_frame, text="Quality:", font=MAIN_FONT)
        self.quality_var = tk.StringVar(value="Auto (Best available)")
        self.quality_menu = tk.OptionMenu(input_frame, self.quality_var, "Auto (Best available)")
        self.quality_label.grid(row=self.QUALITY_ROW_IDX, column=0, sticky="w", padx=5, pady=2)
        self.quality_menu.grid(row=self.QUALITY_ROW_IDX, column=1, sticky="ew", padx=5, pady=2)

        row_idx = self.QUALITY_ROW_IDX + 1
        tk.Label(input_frame, text="Output Filename (optional):", font=MAIN_FONT).grid(row=row_idx, column=0,
                                                                                       sticky="w", padx=5, pady=2)
        self.filename_entry = tk.Entry(input_frame, font=MAIN_FONT)
        self.filename_entry.grid(row=row_idx, column=1, sticky="ew", padx=5, pady=2)

        row_idx += 1
        self.mp3_var = tk.BooleanVar()
        self.mp3_check = tk.Checkbutton(input_frame, text="Convert to MP3", variable=self.mp3_var, font=MAIN_FONT)
        self.mp3_check.grid(row=row_idx, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        row_idx += 1
        self.add_to_queue_button = tk.Button(input_frame, text="Download", command=self._add_current_to_queue,
                                             bg=COLOR_ADD_BUTTON, fg="white", font=BOLD_FONT)
        self.add_to_queue_button.grid(row=row_idx, column=0, columnspan=2, sticky="ew", pady=10)

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
        """Adjusts UI based on selected source (YouTube or XtremeStream)."""
        quality_row = self.QUALITY_ROW_IDX
        referer_row = self.url_entry.grid_info()["row"] + 1

        if value == YOUTUBE_SOURCE:
            self.referer_label.grid_forget()
            self.referer_entry.grid_forget()
            self._update_quality_options_grouped(
                [("Auto (Best available)", "Auto (Best available)")],
                [],
                [],
                [],
                [("1080", "High Quality - 1080p")],
                [("720", "Medium Quality - 720p")],
                [("480", "Low Quality - 480p")]
            )
            self.quality_label.grid(row=quality_row, column=0, sticky="w", padx=5, pady=2)
            self.quality_menu.grid(row=quality_row, column=1, sticky="ew", padx=5, pady=2)
            self._on_url_focus_out()
        else:
            self.quality_label.grid_forget()
            self.quality_menu.grid_forget()
            self.referer_label.grid(row=referer_row, column=0, sticky="w", padx=5, pady=2)
            self.referer_entry.grid(row=referer_row, column=1, sticky="ew", padx=5, pady=2)

        last_input_row = self.mp3_check.grid_info()["row"]
        if self.source_var.get() == XTREAM_SOURCE and self.referer_entry.winfo_ismapped():
            last_input_row = max(last_input_row, self.referer_entry.grid_info()["row"])
        elif self.source_var.get() == YOUTUBE_SOURCE and self.quality_menu.winfo_ismapped():
            last_input_row = max(last_input_row, self.quality_menu.grid_info()["row"])
        self.add_to_queue_button.grid(row=last_input_row + 1, column=0, columnspan=2, sticky="ew", pady=10)

    def _set_status(self, text, color="black"):
        """Updates the main status bar."""
        self.status_bar.config(text=text, fg=color)

    def _add_current_to_queue(self):
        """Adds the current input values as a new download item to the queue."""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Input Error", "Target URL is required.")
            return

        if not (url.startswith("http://") or url.startswith("https://")):
            messagebox.showwarning("Input Error", "Invalid URL. Must start with http:// or https://")
            return

        source = self.source_var.get()
        quality = self.quality_var.get()
        filename_input = self.filename_entry.get().strip()

        filename_provided_by_user = bool(filename_input)

        filename_for_item_data = filename_input if filename_input else f"VideoPlayback_{self.download_item_counter}"

        mp3_conversion = self.mp3_var.get()
        referer = self.referer_entry.get().strip() if source == XTREAM_SOURCE else ""

        self.download_item_counter += 1
        item_id = self.download_item_counter

        item_data = {
            'id': item_id,
            'url': url,
            'quality': quality,
            'filename': filename_for_item_data,
            'mp3_conversion': mp3_conversion,
            'source': source,
            'referer': referer,
            'video_title': 'Fetching Title...',  # This will be updated by fetch_title_async
            'status': 'queued',
            'date_added': time.strftime("%m/%d/%y"),  # Updated format
            'filename_provided_by_user': filename_provided_by_user,
            'elapsed_time_seconds': 0
        }

        new_item = DownloadItem(self, item_data, is_active_item=True)
        self.queued_downloads.append(new_item)
        self.download_items_map[item_id] = new_item
        self.total_downloads_added += 1
        self._refresh_display_order()
        self._set_status(f"Added '{url}' to queue.", COLOR_STATUS_READY)

        self.url_entry.delete(0, END)
        self.filename_entry.delete(0, END)
        self.mp3_var.set(False)
        self.referer_entry.delete(0, END)
        self.url_entry.focus_set()
        self.alert_on_completion_for_session = True

    def _add_to_queue_on_enter(self, event=None):
        """Handles adding to queue when Enter is pressed in URL entry."""
        self._add_current_to_queue()

    def _on_url_focus_out(self, event=None):
        """
        Attempts to pre-fill filename based on URL if not provided by user and source is YouTube.
        Prioritizes fetched title, then sensible fallback.
        """
        url = self.url_entry.get().strip()
        if url and self.source_var.get() == YOUTUBE_SOURCE and not self.filename_entry.get().strip():
            # Create a dummy item to fetch title without adding to queue
            # This is a temporary DownloadItem solely for title fetching preview
            temp_item_data = {
                'id': -1,  # Dummy ID (won't be saved)
                'url': url,
                'quality': self.quality_var.get(),
                'filename': '',  # Empty for fetching
                'mp3_conversion': self.mp3_var.get(),
                'source': self.source_var.get(),
                'referer': self.referer_entry.get().strip(),
                'video_title': 'Fetching Title...',
                'status': 'temp_fetching',
                'date_added': 'N/A',
                'filename_provided_by_user': False,
                'elapsed_time_seconds': 0
            }
            temp_item = DownloadItem(self, temp_item_data, is_active_item=True)  # Treat as active for fetching logic

            def _update_filename_after_fetch():
                # Only update the entry if the user hasn't typed anything in the meantime
                if not self.filename_entry.get().strip():
                    if temp_item.is_title_fetched and temp_item.video_title not in ['Unknown Title',
                                                                                    'Fetching Title...']:
                        sanitized_title = re.sub(r'[\\/:*?"<>|]', '', temp_item.video_title)
                        self.filename_entry.delete(0, END)
                        # Clip preview filename for display if too long
                        preview_filename = sanitized_title[:60] if len(
                            sanitized_title) > 60 else sanitized_title  # Adjusted clip length to fit wider window
                        self.filename_entry.insert(0, preview_filename)
                    else:
                        # Fallback to generic name if title fetch failed or is still pending
                        self.filename_entry.delete(0, END)
                        self.filename_entry.insert(0, f"VideoPlayback_Preview")  # Generic name for preview

            # Fetch title asynchronously and then update filename_entry after a short delay to allow fetch to complete
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
                add_command(f"{text} - {res}p")
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

        # Find the first ready item in the queue that can be started
        next_item_to_start = None
        for i, item in enumerate(self.queued_downloads):
            if item.ready_for_download:  # Only pick if title is fetched and it's ready
                next_item_to_start = self.queued_downloads.pop(i)
                break

        if next_item_to_start and active_count < MAX_CONCURRENT_DOWNLOADS:
            self.active_downloads.append(next_item_to_start)
            next_item_to_start.start_download()
            self.is_queue_processing_active = True
            self.all_downloads_completed.clear()
            self._set_status(f"Starting download for {next_item_to_start.video_title}...", COLOR_STATUS_PROGRESS)
        elif not self.active_downloads and not self.queued_downloads and self.is_queue_processing_active:
            # All downloads are finished
            self.is_queue_processing_active = False
            self.all_downloads_completed.set()

            if self.alert_on_completion_for_session and self.total_downloads_added > 0:
                messagebox.showinfo("Downloads Complete",
                                    f"All {self.completed_downloads_count} downloads finished!")
                self.alert_on_completion_for_session = False
                self.completed_downloads_count = 0
                self.total_downloads_added = 0
            self._set_status("All downloads finished. Ready.", COLOR_STATUS_COMPLETE)
        self.master.after(1000, self._process_queue_loop)

    def download_finished(self, item, final_status):
        """Called by a DownloadItem when its download process completes (success/fail/abort)."""
        if item in self.active_downloads:
            self.active_downloads.remove(item)

        item.status = final_status
        item.date_completed = time.strftime("%m/%d/%y")  # Updated format
        if item.start_time:
            item.elapsed_time_seconds = int(time.time() - item.start_time)
        else:
            item.elapsed_time_seconds = 0

        item.is_active_item = False

        self._save_downloads_to_local_history()

        if final_status == "completed":
            self.completed_downloads_count += 1
            self._set_status(f"Download for '{item.video_title}' completed!", COLOR_STATUS_COMPLETE)
        elif final_status == "aborted":
            self._set_status(f"Download for '{item.video_title}' aborted.", COLOR_STATUS_ABORTED)
        else:
            self._set_status(f"Download for '{item.video_title}' failed.", COLOR_STATUS_FAILED)

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
        self._set_status("Download queue cleared.", COLOR_STATUS_READY)
        messagebox.showinfo("Queue Cleared", "All pending downloads have been cleared.")

    def _clear_finished_history(self):
        """Clears all items from the finished downloads history."""
        if messagebox.askyesno("Clear History", "Are you sure you want to clear all download history? "
                                                "This will not delete the actual downloaded files."):
            ids_to_remove = [item.item_id for item in self.download_items_map.values() if not item.is_active_item]
            for item_id in ids_to_remove:
                self.download_items_map.pop(item_id, None)

            self._save_downloads_to_local_history()
            self._refresh_display_order()
            self._set_status("Download history cleared.", COLOR_STATUS_READY)

    def _refresh_display_order(self):
        """
        Destroys and recreates all download item frames to ensure correct order
        and visibility (active vs. history).
        """
        for widget in self.downloads_frame_inner.winfo_children():
            widget.destroy()

        all_display_items = list(self.download_items_map.values())

        def sort_key(item):
            active_sort = 0 if item.is_active_item else 1
            time_sort = 0

            if item.is_active_item:
                try:
                    # Convert "MM/DD/YY" to a comparable timestamp
                    date_obj = time.strptime(item.date_added, "%m/%d/%y")
                    time_sort = -time.mktime(date_obj)
                except ValueError:
                    time_sort = -time.time()
            elif item.date_completed != 'N/A':
                try:
                    # Convert "MM/DD/YY" to a comparable timestamp
                    date_obj = time.strptime(item.date_completed, "%m/%d/%y")
                    time_sort = -time.mktime(date_obj)
                except ValueError:
                    time_sort = -time.time()
            else:
                time_sort = -time.time()

            return (active_sort, time_sort)

        all_display_items.sort(key=sort_key)

        for item_obj in all_display_items:
            item_obj.parent_frame = self.downloads_frame_inner
            item_obj._build_frame_widgets()
            item_obj.frame.pack(fill="x", padx=5, pady=3)
            item_obj._update_title_label()
            item_obj.update_status(item_obj.status, item_obj._get_status_color(item_obj.status))

        self.downloads_frame_inner.update_idletasks()
        self.downloads_canvas.configure(scrollregion=self.downloads_canvas.bbox("all"))

    def _get_item_data_for_history(self, item_obj):
        """Prepares a dictionary of item data for saving to history."""
        return {
            'id': item_obj.item_id,
            'url': item_obj.url,
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
        """Saves the current finished downloads data (from map) to a local JSON file."""
        history_to_save = [
            self._get_item_data_for_history(item)
            for item in self.download_items_map.values()
            if not item.is_active_item
        ]
        # Sort by date_completed in descending order (newest first) for consistent display order on load
        # Use a tuple for the time.strptime argument to match the new format
        history_to_save.sort(key=lambda x: time.mktime(time.strptime(x['date_completed'], "%m/%d/%y")) if x[
                                                                                                              'date_completed'] != 'N/A' else time.time(),
                             reverse=True)

        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history_to_save, f, indent=4)
        except IOError as e:
            print(f"Error saving history: {e}")

    def _load_downloads_from_local_history(self):
        """Loads download history from a local JSON file on startup."""
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
                        # Before creating DownloadItem, parse date_added and date_completed to ensure
                        # they are in the expected "MM/DD/YY" format for consistency, especially if loading
                        # from an older history file format.
                        # Convert old "MM|DD|YYYY - H:MMpm" format to "MM/DD/YY"
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

