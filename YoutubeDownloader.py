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
# COLOR_TOGGLE_LOG_BUTTON = "#6F42C1" # Purple - Removed as per user request

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

    def __init__(self, parent_frame, app_instance, item_data, is_active_tab=True):
        self.parent_frame = parent_frame
        self.app_instance = app_instance

        # Load data from item_data dictionary
        self.item_id = item_data.get('id')  # Unique ID for this item instance
        self.url = item_data['url']
        self.quality = item_data.get('quality', 'N/A')  # Quality might not be in history items
        self.filename = item_data.get('filename')  # Resolved filename or original proposed
        self.mp3_conversion = item_data.get('mp3_conversion', False)  # Not always needed for history display
        self.source = item_data.get('source', 'N/A')
        self.referer = item_data.get('referer', '')
        self.video_title = item_data.get('video_title', 'Fetching Title...')
        self.status = item_data.get('status', 'queued')  # "queued", "active", "completed", "failed", "aborted"
        self.date_added = item_data.get('date_added', 'N/A')  # New: Date added
        self.date_completed = item_data.get('date_completed', 'N/A')  # Only for finished items
        # New: Track if filename was provided by user or auto-generated
        self.filename_provided_by_user = item_data.get('filename_provided_by_user', False)
        # New: Elapsed time in seconds for history
        self.elapsed_time_seconds = item_data.get('elapsed_time_seconds', 0)

        # Flag to indicate if the video title has been successfully fetched
        # If filename was provided by user, or if loading from history (title is already there),
        # then title is considered fetched.
        self.is_title_fetched = self.filename_provided_by_user or (self.video_title != 'Fetching Title...')

        self.process = None
        self.output_queue = queue.Queue()
        self.start_time = None  # For live elapsed time tracking
        self.last_update_time = None  # For live elapsed time display on active downloads
        self.is_aborted = False
        self.is_merging = False  # Flag to track merging/conversion phase
        self.is_active_tab = is_active_tab  # Flag to determine which tab the item belongs to (for UI placement)

        self._create_widgets()
        self.update_status(self.status, self._get_status_color(self.status))
        self._update_title_label()  # Ensure title is set correctly on init

        # For new items (added via UI), fetch title. For loaded history, title is already there.
        # Only fetch title if not explicitly provided by user AND it's a new/queued item
        if self.is_active_tab and not self.filename_provided_by_user and not self.is_title_fetched:
            self.fetch_title_async()
        elif self.status != 'queued':  # For finished items, set progress based on final state
            if self.status == 'completed':
                self.progress_bar.config(value=100, mode="determinate")
            else:
                self.progress_bar.config(value=0, mode="determinate")
            # For finished items, ensure abort button is not visible or disabled
            if hasattr(self, 'abort_button'):
                self.abort_button.config(state="disabled")  # Disabled for clarity if visible

    def _create_widgets(self):
        """Creates the UI elements for this individual download item."""
        # Use grid for flexible and compact layout
        # Column 0: Title/URL (grows)
        # Column 1: Progress Bar / Status / Date Added (fixed size)
        # Column 2: Elapsed Time / Abort Button / Date Completed (fixed size)
        # Column 3: Open File Button (fixed size, only for finished)

        # Destroy existing frame if it was already packed
        if hasattr(self, 'frame') and self.frame.winfo_exists():
            self.frame.destroy()

        self.frame = tk.Frame(self.parent_frame, bd=2, relief=tk.GROOVE, padx=5, pady=5, bg="#f0f0f0")
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=0)
        self.frame.columnconfigure(2, weight=0)
        self.frame.columnconfigure(3, weight=0)  # Added for the Open File button
        # Use pack with expand=True and fill="x" to ensure it fills parent
        self.frame.pack(fill="x", padx=5, pady=3, expand=True)

        # Common Labels
        self.title_label = tk.Label(self.frame, text="", font=MAIN_FONT, anchor="w", bg="#f0f0f0", wraplength=400,
                                    justify="left")
        self.url_label = tk.Label(self.frame, text="", font=SMALL_FONT, anchor="w", bg="#f0f0f0", wraplength=400,
                                  justify="left")
        self.status_label = tk.Label(self.frame, text="", font=SMALL_FONT, anchor="w", bg="#f0f0f0",
                                     fg=COLOR_STATUS_READY)
        self.date_added_label = tk.Label(self.frame, text=f"Added: {self.date_added}", font=SMALL_FONT, anchor="w",
                                         bg="#f0f0f0")
        self.date_completed_label = tk.Label(self.frame, text=f"Completed: {self.date_completed}", font=SMALL_FONT,
                                             anchor="w", bg="#f0f0f0")
        self.elapsed_time_label = tk.Label(self.frame, text="", font=SMALL_FONT, anchor="e", bg="#f0f0f0")

        # Active Tab Specific Widgets
        self.progress_bar = ttk.Progressbar(self.frame, orient="horizontal", mode="determinate")
        self.abort_button = tk.Button(self.frame, text="Abort", command=self.abort_download, bg=COLOR_ABORT_BUTTON,
                                      fg="white", font=SMALL_FONT)

        # Finished Tab Specific Widgets
        self.open_file_button = tk.Button(self.frame, text="Open File", command=self._open_file_location,
                                          bg=COLOR_OPEN_FILE_BUTTON, fg="white", font=SMALL_FONT)

        if self.is_active_tab:
            # Active Tab Layout
            self.title_label.grid(row=0, column=0, sticky="nw", padx=2, pady=0)
            self.date_added_label.grid(row=0, column=1, sticky="ne", padx=2, pady=0)
            self.progress_bar.grid(row=1, column=0, sticky="ew", padx=2, pady=0)
            self.status_label.grid(row=1, column=1, sticky="w", padx=2, pady=0)
            self.elapsed_time_label.grid(row=1, column=2, sticky="e", padx=2, pady=0)
            self.abort_button.grid(row=1, column=3, sticky="e", padx=2, pady=0)

            # Hide finished-tab-only widgets
            self.url_label.grid_forget()
            self.date_completed_label.grid_forget()
            self.open_file_button.grid_forget()
        else:
            # Finished Tab Layout
            self.title_label.grid(row=0, column=0, columnspan=4, sticky="nw", padx=2, pady=0)
            self.url_label.grid(row=1, column=0, columnspan=4, sticky="nw", padx=2, pady=0)
            self.status_label.grid(row=2, column=0, sticky="w", padx=2, pady=0)
            self.date_added_label.grid(row=2, column=1, sticky="w", padx=2, pady=0)
            self.date_completed_label.grid(row=2, column=2, sticky="e", padx=2, pady=0)
            self.elapsed_time_label.grid(row=2, column=2, sticky="w", padx=2,
                                         pady=0)  # Display elapsed time for history
            self.open_file_button.grid(row=2, column=3, sticky="e", padx=2, pady=0)

            # Hide active-tab-only widgets
            self.progress_bar.grid_forget()
            self.abort_button.grid_forget()

    def _get_status_color(self, status_text):
        """Returns the color based on status text."""
        if status_text == "queued" or "Starting" in status_text:
            return COLOR_STATUS_READY
        elif "Downloading" in status_text or "Converting" in status_text or status_text == "active":
            return COLOR_STATUS_PROGRESS
        elif status_text == "completed":  # Use "completed" for internal logic
            return COLOR_STATUS_COMPLETE
        elif status_text == "failed":
            return COLOR_STATUS_FAILED
        elif status_text == "aborted" or status_text == "cancelled":
            return COLOR_STATUS_ABORTED
        return "black"  # Default color

    def _format_seconds_to_dd_hh_mm_ss(self, total_seconds):
        """
        Formats total seconds into DD|HH|MM or HH|MM|SS.
        If total_seconds >= 1 day, returns DD|HH|MM.
        Else, returns HH|MM|SS.
        """
        if total_seconds < 0:
            total_seconds = 0  # Handle negative values, though should not happen for elapsed time

        days = int(total_seconds // (24 * 3600))
        remaining_seconds = total_seconds % (24 * 3600)
        hours = int(remaining_seconds // 3600)
        remaining_seconds %= 3600
        minutes = int(remaining_seconds // 60)
        seconds = int(remaining_seconds % 60)

        if days > 0:
            return f"{days:02d}|{hours:02d}|{minutes:02d}"
        else:
            return f"{hours:02d}|{minutes:02d}|{seconds:02d}"

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
                                        timeout=10)
                metadata = json.loads(result.stdout)
                self.video_title = metadata.get('title', 'Unknown Title')

                # IMPORTANT FIX: If filename was NOT explicitly set by user, update it with the fetched title
                if not self.filename_provided_by_user:
                    sanitized_title = re.sub(r'[\\/:*?"<>|]', '', self.video_title)
                    self.filename = sanitized_title

                self.is_title_fetched = True  # Title fetched successfully
                self.app_instance.master.after(0, self._update_title_label)

            except FileNotFoundError:
                self.video_title = "Error: yt-dlp.exe not found."
                if not self.filename_provided_by_user:  # Only fallback if not user-provided
                    self.filename = self.url.split('/')[-1].split('?')[0][:50]
                self.is_title_fetched = False  # Mark as not fetched due to error
                self.app_instance.master.after(0, self._update_title_label)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"FileNotFoundError: yt-dlp.exe not found or not in PATH for URL: {self.url}")
            except subprocess.CalledProcessError as e:
                self.video_title = f"Error fetching title: Command failed. {e.stderr.strip()}"
                if not self.filename_provided_by_user:  # Only fallback if not user-provided
                    self.filename = self.url.split('/')[-1].split('?')[0][:50]
                self.is_title_fetched = False  # Mark as not fetched due to error
                self.app_instance.master.after(0, self._update_title_label)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"subprocess.CalledProcessError for URL {self.url}: {e.stderr.strip()}")
            except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
                self.video_title = f"Error fetching title: {e}"
                if not self.filename_provided_by_user:  # Only fallback if not user-provided
                    self.filename = self.url.split('/')[-1].split('?')[0][:50]
                self.is_title_fetched = False  # Mark as not fetched due to error
                self.app_instance.master.after(0, self._update_title_label)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"Decoding/Timeout Error for URL {self.url}: {e}")
            except Exception as e:
                self.video_title = f"Unexpected error fetching title: {e}"
                if not self.filename_provided_by_user:  # Only fallback if not user-provided
                    self.filename = self.url.split('/')[-1].split('?')[0][:50]
                self.is_title_fetched = False  # Mark as not fetched due to error
                self.app_instance.master.after(0, self._update_title_label)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"General Error fetching title for URL {self.url}: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_title_label(self):
        """Updates the title label on the UI with the fetched title."""
        display_name = self.video_title if self.video_title and self.video_title != 'Fetching Title...' else (
            os.path.basename(self.filename) if self.filename else self.url)
        if len(display_name) > 60:  # Smaller clip for title to make space
            display_name = display_name[:57] + "..."

        if self.is_active_tab:
            self.title_label.config(text=f"{display_name} ({self.source})")
            self.date_added_label.config(text=f"Added: {self.date_added}")
            # Live elapsed time update is handled in _parse_output_for_progress and _process_queue_loop
        else:  # Finished tab display
            # Update labels based on finished item structure
            self.title_label.config(text=f"Title: {display_name}")

            display_url = self.url
            if len(display_url) > 70:  # Clip URL for display
                display_url = display_url[:67] + "..."
            self.url_label.config(text=f"URL: {display_url}")

            self.date_added_label.config(text=f"Added: {self.date_added}")
            self.date_completed_label.config(text=f"Completed: {self.date_completed}")
            self.elapsed_time_label.config(
                text=f"Time: {self._format_seconds_to_dd_hh_mm_ss(self.elapsed_time_seconds)}")

    def start_download(self):
        """Starts the yt-dlp process for this item in a new thread."""
        self.is_aborted = False
        self.is_merging = False
        self.start_time = time.time()  # Record start time
        self.last_update_time = time.time()  # Reset last update time for live display
        self.update_status("active", COLOR_STATUS_PROGRESS)  # Update status to 'active'
        self.abort_button.config(state="normal")
        self.progress_bar.config(value=0)
        self.progress_bar.config(mode="determinate")

        # Initial elapsed time display for active downloads
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
        command += ["--paths", f"temp:{temp_dir}"]

        out_name = self.filename  # This is the resolved filename

        if self.mp3_conversion:
            command += ["--extract-audio", "--audio-format", "mp3", "--output",
                        os.path.join(downloads_dir, out_name + ".%(ext)s")]
        else:
            command += ["--recode-video", "mp4", "--output", os.path.join(downloads_dir, out_name + ".%(ext)s")]

        if self.source == YOUTUBE_SOURCE:
            if "Auto (Best available)" in self.quality:
                command += ['-f', 'bestvideo+bestaudio/best']
            elif self.quality == "High Quality - 1080p":
                command += ['-f', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]']
            elif self.quality == "Medium Quality - 720p":
                command += ['-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]']
            elif self.quality == "Low Quality - 480p":
                command += ['-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]']
            elif "Combined" in self.quality:
                res = re.search(r'(\d+)p', self.quality).group(1)
                command += ['-f', f'bestvideo[height<={res}]+bestaudio/best[height<={res}]']
            elif "Video Only" in self.quality:
                res = re.search(r'(\d+)p', self.quality).group(1)
                command += ['-f', f'bestvideo[height<={res}]']

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
                # If log window is visible, append line to it
                if self.app_instance.log_window_visible and self.app_instance.log_text:
                    self.app_instance.master.after(0, lambda l=line: self._append_to_log(l))

                self._parse_output_for_progress(line)
                # Update elapsed time live
                if self.start_time:  # Only update if download has started
                    elapsed = time.time() - self.start_time
                    self.app_instance.master.after(0, lambda e=elapsed: self.elapsed_time_label.config(
                        text=f"Time: {self._format_seconds_to_dd_hh_mm_ss(e)}"))

            rc = self.process.wait()
            # Stop indeterminate progress bar if it was running
            if self.is_merging:
                self.progress_bar.stop()

            if self.is_aborted:
                final_status = "aborted"
                self.update_status("aborted", COLOR_STATUS_ABORTED)
            elif rc == 0:
                final_status = "completed"
                self.update_status("completed", COLOR_STATUS_COMPLETE)
                self.progress_bar.config(value=100, mode="determinate")
            else:
                final_status = "failed"
                self.update_status("failed", COLOR_STATUS_FAILED)

        except FileNotFoundError:
            final_status = "failed"
            self.update_status("failed", COLOR_STATUS_FAILED)  # Use internal status names
            if self.app_instance.log_window_visible and self.app_instance.log_text:
                self.app_instance.master.after(0, lambda: self._append_to_log(
                    "ERROR: yt-dlp.exe not found or not in PATH.\n"))
            print(f"FileNotFoundError: yt-dlp.exe not found or not in PATH for download of URL: {self.url}")
        except Exception as e:
            final_status = "failed"
            self.update_status("failed", COLOR_STATUS_FAILED)
            if self.app_instance.log_window_visible and self.app_instance.log_text:
                self.app_instance.master.after(0, lambda: self._append_to_log(f"ERROR during yt-dlp execution: {e}\n"))
            print(f"Error during yt-dlp execution for URL {self.url}: {e}")
        finally:
            self.process = None
            self.abort_button.config(state="disabled")
            temp_path = os.path.join(os.getcwd(), DOWNLOADS_DIR, TEMP_SUBDIR, str(self.item_id))
            if os.path.exists(temp_path):
                shutil.rmtree(temp_path, ignore_errors=True)

            self.app_instance.download_finished(self, final_status)

    def _append_to_log(self, text):
        """Appends text to the log window's ScrolledText widget."""
        if self.app_instance.log_text and self.app_instance.log_window.winfo_exists():
            self.app_instance.log_text.config(state=tk.NORMAL)  # Enable writing
            self.app_instance.log_text.insert(END, text)
            self.app_instance.log_text.see(END)  # Auto-scroll to the end
            self.app_instance.log_text.config(state=tk.DISABLED)  # Disable writing

    def _parse_output_for_progress(self, line):
        """Parses a line of yt-dlp output for progress, speed, and ETA."""
        match_percent = re.search(
            r'\[download\]\s+(\d+\.\d+)%|^[A-Za-z]+\s+.*?(\d+\.\d+)%\s+at\s+.*?(?:ETA\s+(\d{2}:\d{2}))?', line)
        if match_percent:
            percent_str = match_percent.group(1) if match_percent.group(1) else match_percent.group(2)
            if percent_str:
                percent = float(percent_str)
                if self.is_merging:
                    self.progress_bar.stop()
                    self.progress_bar.config(mode="determinate")
                    self.is_merging = False

                self.progress_bar.config(value=percent)

                speed_match = re.search(r'at\s+([0-9\.]+[KMG]?iB/s|\S+)(?:\s+ETA\s+(\d{2}:\d{2}))?', line)
                speed = speed_match.group(1) if speed_match and speed_match.group(1) else 'N/A'
                eta = speed_match.group(2) if speed_match and speed_match.group(2) else 'N/A'

                self.update_status(f"Downloading... {percent:.1f}% ({speed}, ETA {eta})", COLOR_STATUS_PROGRESS)
            return

        if "merging formats" in line.lower() or "ffmpeg" in line.lower() or "postprocessing" in line.lower() or "extractaudio" in line.lower():
            if not self.is_merging:
                self.update_status("Converting/Merging...", COLOR_STATUS_PROGRESS)
                self.progress_bar.config(mode="indeterminate")
                self.progress_bar.start()
                self.is_merging = True
            return

        if "downloading" in line.lower() and not self.is_merging:
            self.update_status("Downloading...", COLOR_STATUS_PROGRESS)
            return

    def update_status(self, text, color):
        """Updates the status label for this download item."""
        self.status_label.config(text=text.capitalize(), fg=color)  # Capitalize for display
        self.status = text  # Keep item's internal status updated

    def abort_download(self):
        """Aborts the currently running download process."""
        self.is_aborted = True
        if self.process:
            try:
                self.process.kill()
                self.update_status("aborted", COLOR_STATUS_ABORTED)
                if self.is_merging:
                    self.progress_bar.stop()
                    self.progress_bar.config(mode="determinate")
            except Exception:
                self.update_status("failed", COLOR_STATUS_FAILED)
        else:
            self.update_status("aborted", COLOR_STATUS_ABORTED)
            self.app_instance.remove_from_queue(self)  # Pass the item object

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
                # For Windows, use explorer.exe with /select,
                # but it requires a path with forward slashes for some reason.
                subprocess.Popen(f'explorer /select,"{full_filepath.replace("/", "\\")}"')
            elif sys.platform == "darwin":
                # For macOS, use 'open -R' to reveal in Finder
                subprocess.Popen(["open", "-R", full_filepath])
            else:
                # For Linux/other Unix-like systems, use xdg-open
                subprocess.Popen(["xdg-open", os.path.dirname(full_filepath)])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open file location: {e}")


class YTDLPGUIApp:
    def __init__(self, master):
        self.master = master
        self._setup_window(master)

        self._configure_yt_dlp_path()
        self._create_menus()  # New: Create menus

        self._create_widgets()
        self._initialize_download_management()
        self._load_downloads_from_local_history()  # Load history on startup

        self.master.after(100, self._process_queue_loop)
        self.on_source_change(YOUTUBE_SOURCE)

        # Log Window variables
        self.log_window = None
        self.log_text = None
        self.log_window_visible = False

    def _setup_window(self, master):
        master.title("YouTube Downloader powered by yt-dlp")
        master.geometry("800x650")  # Increased width for tabs
        master.resizable(True, True)
        try:
            master.iconbitmap("ico.ico")
        except Exception:
            pass

    def _create_menus(self):
        """Creates the application menus."""
        menubar = tk.Menu(self.master)
        self.master.config(menu=menubar)

        # Help Menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About Versions...", command=self._show_versions_info)

        # View Menu for logs
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
            # yt-dlp version
            yt_dlp_result = subprocess.run([self.yt_dlp_path, "--version"], capture_output=True, text=True, check=True,
                                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                                           timeout=5)
            yt_dlp_version = yt_dlp_result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

        try:
            # ffmpeg version (yt-dlp automatically uses it for merging/conversion)
            ffmpeg_result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True,
                                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                                           timeout=5)
            ffmpeg_version_lines = ffmpeg_result.stdout.strip().split('\n')
            if ffmpeg_version_lines:
                ffmpeg_version = ffmpeg_version_lines[0]  # Get the first line of ffmpeg output
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
                self.log_window.protocol("WM_DELETE_WINDOW", self._on_log_window_close)  # Handle close button

                self.log_text = scrolledtext.ScrolledText(self.log_window, wrap=tk.WORD, font=MONO_FONT, bg="black",
                                                          fg="lightgreen", insertbackground="white")
                self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
                self.log_text.config(state=tk.DISABLED)  # Make it read-only
            self.log_window.deiconify()  # Show the window
        else:
            if self.log_window and self.log_window.winfo_exists():
                self.log_window.withdraw()  # Hide the window

    def _on_log_window_close(self):
        """Handles the log window close button, updating the toggle variable."""
        self.log_toggle_var.set(False)
        self.log_window_visible = False
        if self.log_window:
            self.log_window.withdraw()  # Hide the window

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

        # --- Input Section ---
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
        self.url_entry.bind("<Return>", self._add_to_queue_on_enter)  # Binding
        self.url_entry.bind("<FocusOut>", self._on_url_focus_out)

        # Fixed row index for quality controls
        self.QUALITY_ROW_IDX = row_idx + 1
        self.quality_label = tk.Label(input_frame, text="Quality:", font=MAIN_FONT)
        self.quality_var = tk.StringVar(value="Auto (Best available)")
        self.quality_menu = tk.OptionMenu(input_frame, self.quality_var, "Auto (Best available)")  # Placeholder
        self.quality_label.grid(row=self.QUALITY_ROW_IDX, column=0, sticky="w", padx=5, pady=2)
        self.quality_menu.grid(row=self.QUALITY_ROW_IDX, column=1, sticky="ew", padx=5, pady=2)

        row_idx = self.QUALITY_ROW_IDX + 1  # Update row_idx to be after quality controls
        tk.Label(input_frame, text="Output Filename (optional):", font=MAIN_FONT).grid(row=row_idx, column=0,
                                                                                       sticky="w", padx=5, pady=2)
        self.filename_entry = tk.Entry(input_frame, font=MAIN_FONT)
        self.filename_entry.grid(row=row_idx, column=1, sticky="ew", padx=5, pady=2)

        row_idx += 1
        self.mp3_var = tk.BooleanVar()
        self.mp3_check = tk.Checkbutton(input_frame, text="Convert to MP3", variable=self.mp3_var, font=MAIN_FONT)
        self.mp3_check.grid(row=row_idx, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        row_idx += 1
        # Renamed "Add to Queue" to "Download"
        self.add_to_queue_button = tk.Button(input_frame, text="Download", command=self._add_current_to_queue,
                                             bg=COLOR_ADD_BUTTON, fg="white", font=BOLD_FONT)
        self.add_to_queue_button.grid(row=row_idx, column=0, columnspan=2, sticky="ew", pady=10)

        # --- Queue Management Section (removed Start Queue button) ---
        queue_control_frame = tk.Frame(self.main_frame)
        queue_control_frame.pack(fill="x", pady=5)

        self.clear_queue_button = tk.Button(queue_control_frame, text="Clear Queue", command=self._clear_queue,
                                            bg=COLOR_CLEAR_BUTTON, fg="black", font=BOLD_FONT)
        self.clear_queue_button.pack(side="left", expand=True, fill="x", padx=2)

        self.open_downloads_button = tk.Button(queue_control_frame, text="Open Downloads",
                                               command=self._open_downloads_folder, bg=COLOR_OPEN_FOLDER_BUTTON,
                                               fg="white", font=BOLD_FONT)
        self.open_downloads_button.pack(side="left", expand=True, fill="x", padx=2)

        self.clear_history_button = tk.Button(queue_control_frame, text="Clear History",
                                              command=self._clear_finished_history, bg=COLOR_CLEAR_BUTTON, fg="black",
                                              font=BOLD_FONT)
        self.clear_history_button.pack(side="left", expand=True, fill="x", padx=2)

        # Removed the Toggle Log button as requested
        # self.toggle_log_button = tk.Button(queue_control_frame, text="Toggle Log", command=self._toggle_log_window, bg=COLOR_TOGGLE_LOG_BUTTON, fg="white", font=BOLD_FONT)
        # self.toggle_log_button.pack(side="left", expand=True, fill="x", padx=2)

        # --- Download Items Display Area with Tabs ---
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.pack(fill="both", expand=True, pady=5)

        # Active Downloads Tab
        self.active_tab_frame = tk.Frame(self.notebook)
        self.notebook.add(self.active_tab_frame, text="Active Downloads")
        self.active_tab_frame.grid_rowconfigure(0, weight=1)
        self.active_tab_frame.grid_columnconfigure(0, weight=1)

        self.active_canvas = tk.Canvas(self.active_tab_frame, bg="white", highlightthickness=0)
        self.active_canvas.grid(row=0, column=0, sticky="nsew")
        self.active_scroll_y = tk.Scrollbar(self.active_tab_frame, orient="vertical", command=self.active_canvas.yview)
        self.active_scroll_y.grid(row=0, column=1, sticky="ns")
        self.active_canvas.config(yscrollcommand=self.active_scroll_y.set)
        self.active_downloads_frame_inner = tk.Frame(self.active_canvas, bg="white")
        self.active_canvas_window_id = self.active_canvas.create_window((0, 0),
                                                                        window=self.active_downloads_frame_inner,
                                                                        anchor="nw",
                                                                        width=self.active_canvas.winfo_width())
        self.active_downloads_frame_inner.bind("<Configure>", lambda e: self.active_canvas.configure(
            scrollregion=self.active_canvas.bbox("all")))
        self.active_canvas.bind('<Configure>', self._on_active_canvas_resize)
        # Added mouse wheel scrolling for active downloads
        self.active_canvas.bind('<MouseWheel>', self._on_mousewheel_active)  # Windows/macOS
        self.active_canvas.bind('<Button-4>', self._on_mousewheel_active)  # Linux scroll up
        self.active_canvas.bind('<Button-5>', self._on_mousewheel_active)  # Linux scroll down

        # Finished Downloads Tab
        self.finished_tab_frame = tk.Frame(self.notebook)
        self.notebook.add(self.finished_tab_frame, text="Finished Downloads")
        self.finished_tab_frame.grid_rowconfigure(0, weight=1)
        self.finished_tab_frame.grid_columnconfigure(0, weight=1)

        self.finished_canvas = tk.Canvas(self.finished_tab_frame, bg="white", highlightthickness=0)
        self.finished_canvas.grid(row=0, column=0, sticky="nsew")
        self.finished_scroll_y = tk.Scrollbar(self.finished_tab_frame, orient="vertical",
                                              command=self.finished_canvas.yview)
        self.finished_scroll_y.grid(row=0, column=1, sticky="ns")
        self.finished_canvas.config(yscrollcommand=self.finished_scroll_y.set)
        self.finished_downloads_frame_inner = tk.Frame(self.finished_canvas, bg="white")
        self.finished_canvas_window_id = self.finished_canvas.create_window((0, 0),
                                                                            window=self.finished_downloads_frame_inner,
                                                                            anchor="nw",
                                                                            width=self.finished_canvas.winfo_width())
        self.finished_downloads_frame_inner.bind("<Configure>", lambda e: self.finished_canvas.configure(
            scrollregion=self.finished_canvas.bbox("all")))
        self.finished_canvas.bind('<Configure>', self._on_finished_canvas_resize)
        # Added mouse wheel scrolling for finished downloads
        self.finished_canvas.bind('<MouseWheel>', self._on_mousewheel_finished)  # Windows/macOS
        self.finished_canvas.bind('<Button-4>', self._on_mousewheel_finished)  # Linux scroll up
        self.finished_canvas.bind('<Button-5>', self._on_mousewheel_finished)  # Linux scroll down

        # --- Status Bar ---
        self.status_bar = tk.Label(self.master, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W, font=SMALL_FONT,
                                   fg=COLOR_STATUS_READY)
        self.status_bar.pack(side="bottom", fill="x")

    def _on_mousewheel_active(self, event):
        self.active_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"  # Prevent event propagation

    def _on_mousewheel_finished(self, event):
        self.finished_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"  # Prevent event propagation

    def _on_active_canvas_resize(self, event):
        """Adjusts the width of the inner frame for active downloads when the canvas resizes."""
        self.active_canvas.itemconfig(self.active_canvas_window_id, width=event.width)
        self.active_canvas.configure(scrollregion=self.active_canvas.bbox("all"))

    def _on_finished_canvas_resize(self, event):
        """Adjusts the width of the inner frame for finished downloads when the canvas resizes."""
        self.finished_canvas.itemconfig(self.finished_canvas_window_id, width=event.width)
        self.finished_canvas.configure(scrollregion=self.finished_canvas.bbox("all"))

    def _initialize_download_management(self):
        self.queued_downloads = []  # List of DownloadItem objects (waiting to start)
        self.active_downloads = []  # List of DownloadItem objects (currently downloading)
        self.download_items_map = {}  # {item_id: DownloadItem object} for easy lookup of all items

        self.finished_downloads_data = []  # List of dictionaries for finished downloads history

        self.download_item_counter = 0  # Used for generating unique local IDs
        self.completed_downloads_count = 0
        self.total_downloads_added = 0
        # self.is_queue_processing_active is no longer explicitly toggled by a button,
        # it's implicitly true as long as there are items to process and slots available.
        # However, we keep it as a flag to control the main loop's behavior
        self.is_queue_processing_active = False
        # Initialize as cleared. It will be set when a started queue actually completes.
        self.all_downloads_completed = threading.Event()

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
                [], [], [],  # Dynamic qualities will be fetched
                [("1080", "High Quality - 1080p")],  # Fixed High Quality
                [("720", "Medium Quality - 720p")],  # Fixed Medium Quality
                [("480", "Low Quality - 480p")]  # Fixed Low Quality
            )
            self.quality_label.grid(row=quality_row, column=0, sticky="w", padx=5, pady=2)
            self.quality_menu.grid(row=quality_row, column=1, sticky="ew", padx=5, pady=2)

            self._on_url_focus_out()
        else:  # XtremeStream
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
        filename_input = self.filename_entry.get().strip()  # Get filename from input

        # Determine if filename was provided by user
        filename_provided_by_user = bool(filename_input)

        # Initial filename for the DownloadItem before title is fetched.
        # This will be updated once fetch_title_async completes if not user-provided.
        filename = filename_input if filename_provided_by_user else url.split('/')[-1].split('?')[0][:50]

        mp3_conversion = self.mp3_var.get()
        referer = self.referer_entry.get().strip() if source == XTREAM_SOURCE else ""

        self.download_item_counter += 1
        item_id = f"dl_{self.download_item_counter}_{int(time.time())}"  # Unique ID for this item
        # Updated date format to MM|DD|YYYY - H:MMpm
        current_time_str = time.strftime("%m|%d|%Y - %I:%M%p")

        new_download_data = {
            'id': item_id,
            'url': url,
            'quality': quality,
            'filename': filename,  # Use the determined filename
            'mp3_conversion': mp3_conversion,
            'source': source,
            'referer': referer,
            'status': 'queued',
            'video_title': 'Fetching Title...',  # Will be updated async
            'date_added': current_time_str,  # New: date added
            'filename_provided_by_user': filename_provided_by_user,  # New: Store this flag
            'elapsed_time_seconds': 0  # Initialize elapsed time for new items
        }

        new_item = DownloadItem(self.active_downloads_frame_inner, self, new_download_data, is_active_tab=True)
        self.queued_downloads.append(new_item)
        self.download_items_map[new_item.item_id] = new_item
        self.total_downloads_added += 1

        self._set_status(f"Added '{url[:40]}...' to queue. Queue size: {len(self.queued_downloads)}",
                         COLOR_STATUS_READY)
        self._update_queue_control_buttons()  # This is the old name, will be adjusted.

        # Clear input fields after adding
        self.url_entry.delete(0, END)
        self.filename_entry.delete(0, END)
        if self.source_var.get() == XTREAM_SOURCE:
            self.referer_entry.delete(0, END)

        # Reset quality dropdown to default "Auto (Best available)" after adding
        self._update_quality_options_grouped(
            [("Auto (Best available)", "Auto (Best available)")],
            [], [], [],
            [("1080", "High Quality - 1080p")],
            [("720", "Medium Quality - 720p")],
            [("480", "Low Quality - 480p")]
        )

        self.active_downloads_frame_inner.update_idletasks()
        self.active_canvas.yview_moveto(1.0)
        # Call _process_queue. If slots are free, it will start. This is intended for concurrency.
        self._process_queue()

    def _add_to_queue_on_enter(self, event=None):
        """Handler for 'Return' key press in URL entry."""
        self._add_current_to_queue()

    def _on_url_focus_out(self, event=None):
        """Triggered when URL entry loses focus; fetches available qualities."""
        url = self.url_entry.get().strip()
        if url and (url.startswith("http://") or url.startswith("https://")):
            self._fetch_and_update_quality_options(url)
        elif self.source_var.get() == YOUTUBE_SOURCE:
            self._update_quality_options_grouped(
                [("Auto (Best available)", "Auto (Best available)")],
                [], [], [],
                [("1080", "High Quality - 1080p")],
                [("720", "Medium Quality - 720p")],
                [("480", "Low Quality - 480p")]
            )

    def _fetch_and_update_quality_options(self, url):
        """Fetches available formats from yt-dlp and updates the quality OptionMenu."""
        self.quality_var.set("Fetching qualities...")  # Provide immediate feedback

        fixed_high_q = [("1080", "High Quality - 1080p")]
        fixed_medium_q = [("720", "Medium Quality - 720p")]
        fixed_low_q = [("480", "Low Quality - 480p")]

        def _fetch_formats():
            try:
                command = [
                    self.yt_dlp_path,
                    "--list-formats",
                    "--print-json",
                    url
                ]
                result = subprocess.run(command, capture_output=True, text=True, check=True,
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                                        timeout=15)
                metadata = json.loads(result.stdout)
                formats = metadata.get('formats', [])

                high_qualities_dynamic = []
                medium_qualities_dynamic = []
                low_qualities_dynamic = []

                for fmt in formats:
                    height = fmt.get('height')
                    vcodec = fmt.get('vcodec')
                    acodec = fmt.get('acodec')

                    if height and height != 'None' and isinstance(height, int):
                        label = f"{height}p"
                        if vcodec != 'none' and acodec != 'none':
                            label += " (Combined)"
                        elif vcodec != 'none':
                            label += " (Video Only)"
                        else:
                            continue

                        if height >= 1080:
                            high_qualities_dynamic.append((height, label))
                        elif 720 <= height < 1080:
                            medium_qualities_dynamic.append((height, label))
                        elif height < 720:
                            low_qualities_dynamic.append((height, label))

                high_qualities_dynamic.sort(key=lambda x: x[0], reverse=True)
                medium_qualities_dynamic.sort(key=lambda x: x[0], reverse=True)
                low_qualities_dynamic.sort(key=lambda x: x[0], reverse=True)

                auto_option = [("Auto (Best available)", "Auto (Best available)")]

                self.master.after(0, lambda: self._update_quality_options_grouped(
                    auto_option,
                    high_qualities_dynamic,
                    medium_qualities_dynamic,
                    low_qualities_dynamic,
                    fixed_high_q,
                    fixed_medium_q,
                    fixed_low_q
                ))
            except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError,
                    subprocess.TimeoutExpired) as e:
                self.master.after(0, lambda: self._update_quality_options_grouped(
                    [("Auto (Best available)", "Auto (Best available)")],
                    [], [], [],
                    fixed_high_q, fixed_medium_q, fixed_low_q,
                    error_message="Error fetching qualities"
                ))
                print(f"Error fetching formats for {url}: {e}")
            except Exception as e:
                self.master.after(0, lambda: self._update_quality_options_grouped(
                    [("Auto (Best available)", "Auto (Best available)")],
                    [], [], [],
                    fixed_high_q, fixed_medium_q, fixed_low_q,
                    error_message="Unexpected error"
                ))
                print(f"Unexpected error fetching formats: {e}")

        threading.Thread(target=_fetch_formats, daemon=True).start()

    def _update_quality_options_grouped(self, auto_options, high_q_dynamic, medium_q_dynamic, low_q_dynamic,
                                        high_q_fixed, medium_q_fixed, low_q_fixed, error_message=None):
        """Updates the OptionMenu with new grouped quality options."""
        current_selection = self.quality_var.get()

        self.quality_menu['menu'].delete(0, 'end')

        if error_message:
            self.quality_menu['menu'].add_command(label=error_message, state="disabled")
            self.quality_var.set(error_message)
            return

        for _, label in auto_options:
            self.quality_menu['menu'].add_command(label=label, command=tk._setit(self.quality_var, label))

        has_fixed_qualities = False
        if high_q_fixed or medium_q_fixed or low_q_fixed:
            has_fixed_qualities = True
            self.quality_menu['menu'].add_separator()
            self.quality_menu['menu'].add_command(label="--- Standard Qualities ---", state="disabled")

            for _, label in high_q_fixed:
                self.quality_menu['menu'].add_command(label=label, command=tk._setit(self.quality_var, label))
            for _, label in medium_q_fixed:
                self.quality_menu['menu'].add_command(label=label, command=tk._setit(self.quality_var, label))
            for _, label in low_q_fixed:
                self.quality_menu['menu'].add_command(label=label, command=tk._setit(self.quality_var, label))

        if high_q_dynamic or medium_q_dynamic or low_q_dynamic:
            if has_fixed_qualities:
                self.quality_menu['menu'].add_separator()
            self.quality_menu['menu'].add_command(label="--- Dynamic Qualities ---", state="disabled")

            if high_q_dynamic:
                self.quality_menu['menu'].add_command(label="High Qualities:", state="disabled")
                for _, label in high_q_dynamic:
                    self.quality_menu['menu'].add_command(label=label, command=tk._setit(self.quality_var, label))
            if medium_q_dynamic:
                self.quality_menu['menu'].add_command(label="Medium Qualities:", state="disabled")
                for _, label in medium_q_dynamic:
                    self.quality_menu['menu'].add_command(label=label, command=tk._setit(self.quality_var, label))
            if low_q_dynamic:
                self.quality_menu['menu'].add_command(label="Low Qualities:", state="disabled")
                for _, label in low_q_dynamic:
                    self.quality_menu['menu'].add_command(label=label, command=tk._setit(self.quality_var, label))

        all_display_options = [label for _, label in auto_options] + \
                              [label for _, label in high_q_fixed] + \
                              [label for _, label in medium_q_fixed] + \
                              [label for _, label in low_q_fixed] + \
                              [label for _, label in high_q_dynamic] + \
                              [label for _, label in medium_q_dynamic] + \
                              [label for _, label in low_q_dynamic]

        if current_selection in all_display_options:
            self.quality_var.set(current_selection)
        elif all_display_options:
            self.quality_var.set(all_display_options[0])
        else:
            self.quality_var.set("No qualities found")

    def _start_queue_processing(self):
        """Activates queue processing. This method is now implicitly called by _process_queue."""
        self.is_queue_processing_active = True
        self.all_downloads_completed.clear()  # Clear the flag when queue processing starts
        self._set_status("Queue processing started...", COLOR_STATUS_PROGRESS)
        self._process_queue()  # Kick off initial processing

    def _process_queue_loop(self):
        """Main loop for polling individual download item queues and managing concurrency."""
        for item in list(self.active_downloads):
            try:
                while True:
                    _ = item.output_queue.get_nowait()
            except queue.Empty:
                pass
            # Update elapsed time for active downloads if not already being updated by subprocess output
            # This ensures elapsed time updates even if yt-dlp isn't printing progress (e.g., during initial setup)
            if item.start_time and item.is_active_tab:  # Check is_active_tab to ensure it's still in the active view
                elapsed = time.time() - item.start_time
                # Only update elapsed_time_label if it's still mapped to the screen (active tab)
                if item.elapsed_time_label.winfo_exists() and item.elapsed_time_label.winfo_ismapped():
                    item.elapsed_time_label.config(text=f"Time: {item._format_seconds_to_dd_hh_mm_ss(elapsed)}")

        # Keep processing queue if there are items or active downloads
        if self.queued_downloads or self.active_downloads:
            self.is_queue_processing_active = True  # Ensure this flag stays true
            self._process_queue()
        else:
            self.is_queue_processing_active = False  # No more items, set to false

        # Only show completion alert if queue processing was active AND now all are done.
        # Check if all downloads have truly finished and the processing was active.
        if not self.is_queue_processing_active and not self.queued_downloads and not self.active_downloads:
            if not self.all_downloads_completed.is_set():  # Only show if it wasn't already shown for this cycle
                self.all_downloads_completed.set()
                self._show_overall_completion_alert()
                self._set_status("All downloads complete!", COLOR_STATUS_COMPLETE)
                self.total_downloads_added = 0
                self.completed_downloads_count = 0
                self.is_queue_processing_active = False  # Reset this flag
                self._update_queue_control_buttons()

        self.master.after(100, self._process_queue_loop)

    def _process_queue(self):
        """
        Checks for available slots, handles file conflicts, and starts downloads from the queue.
        This method is called repeatedly by the main loop.
        """
        self.is_queue_processing_active = True  # Ensure processing is considered active when this is called

        # Iterate over a copy of queued_downloads so we can modify the original list
        for i, next_item in enumerate(list(self.queued_downloads)):
            if len(self.active_downloads) >= MAX_CONCURRENT_DOWNLOADS:
                break  # Max concurrent downloads reached

            # Only process items where filename is explicitly provided OR title has been fetched
            if not next_item.filename_provided_by_user and not next_item.is_title_fetched:
                # This item is not ready yet, skip it for this cycle
                continue

            # Determine the expected file extension based on mp3_conversion
            expected_ext = ".mp3" if next_item.mp3_conversion else ".mp4"

            # Calculate the full expected file path (assuming yt-dlp output naming conventions)
            downloads_path = os.path.join(os.getcwd(), DOWNLOADS_DIR)
            proposed_filepath = os.path.join(downloads_path, next_item.filename + expected_ext)

            if os.path.exists(proposed_filepath):
                # File conflict detected, show dialog
                self._set_status(f"File '{os.path.basename(proposed_filepath)}' already exists. Awaiting user choice.",
                                 "orange")
                # Remove from queued_downloads immediately to avoid re-processing in the loop
                self.queued_downloads.remove(next_item)
                self._show_file_conflict_dialog(next_item, proposed_filepath)
                # After dialog, _handle_file_conflict_choice will either start download or move to history.
                # It will also call _process_queue again. So we can return here.
                return
            else:
                # No conflict, proceed with download
                self.queued_downloads.remove(next_item)  # Officially remove from queue
                self.active_downloads.append(next_item)
                next_item.start_download()
                display_title = next_item.video_title if next_item.video_title != 'Fetching Title...' else next_item.url
                self._set_status(
                    f"Starting download for '{display_title[:40]}...'. Active: {len(self.active_downloads)}",
                    COLOR_STATUS_PROGRESS)
                self._update_queue_control_buttons()

    def _show_file_conflict_dialog(self, download_item, existing_filepath):
        """
        Displays a custom dialog for file conflict resolution.
        Options: Overwrite, Keep Both, Cancel.
        """
        dialog = tk.Toplevel(self.master)
        dialog.title("File Exists")
        dialog.transient(self.master)  # Make it a transient window of the master
        dialog.grab_set()  # Make it modal
        dialog.resizable(False, False)

        filename_display = os.path.basename(existing_filepath)

        tk.Label(dialog, text=f"The file '{filename_display}' already exists.\nWhat would you like to do?",
                 font=MAIN_FONT, wraplength=300, justify="center", padx=10, pady=10).pack()

        button_frame = tk.Frame(dialog, padx=10, pady=5)
        button_frame.pack()

        result = tk.StringVar(value="")  # To store the user's choice

        def on_choice(choice):
            result.set(choice)
            dialog.destroy()  # Close the dialog

        tk.Button(button_frame, text="Overwrite", bg=COLOR_ABORT_BUTTON, fg="white", font=BOLD_FONT,
                  command=lambda: on_choice("overwrite")).pack(side="left", padx=5, pady=5)
        tk.Button(button_frame, text="Keep Both", bg=COLOR_ADD_BUTTON, fg="white", font=BOLD_FONT,
                  # Changed color to Add Button green
                  command=lambda: on_choice("keep_both")).pack(side="left", padx=5, pady=5)
        tk.Button(button_frame, text="Cancel", bg=COLOR_CLEAR_BUTTON, fg="black", font=BOLD_FONT,
                  command=lambda: on_choice("cancel")).pack(side="left", padx=5, pady=5)

        dialog.update_idletasks()
        x = self.master.winfo_x() + (self.master.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.master.winfo_y() + (self.master.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        self.master.wait_window(dialog)

        choice = result.get()
        self._handle_file_conflict_choice(choice, download_item, existing_filepath)

    def _handle_file_conflict_choice(self, choice, download_item, existing_filepath):
        """Processes the user's choice from the file conflict dialog."""
        if choice == "overwrite":
            self.active_downloads.append(download_item)
            download_item.start_download()
            display_title = download_item.video_title if download_item.video_title != 'Fetching Title...' else download_item.url
            self._set_status(f"Overwriting for '{display_title[:40]}...'. Active: {len(self.active_downloads)}",
                             COLOR_STATUS_PROGRESS)
        elif choice == "keep_both":
            original_filename_no_ext, ext = os.path.splitext(os.path.basename(existing_filepath))

            match = re.match(r"^(.*?)( \(\d+\))?$", original_filename_no_ext)
            base_name_for_renaming = match.group(1) if match else original_filename_no_ext

            new_filename = self._generate_unique_filename(base_name_for_renaming, download_item.mp3_conversion)
            download_item.filename = new_filename  # Update the item's filename

            self.active_downloads.append(download_item)
            download_item.start_download()
            self._set_status(f"Starting download (renamed to '{new_filename}'). Active: {len(self.active_downloads)}",
                             COLOR_STATUS_PROGRESS)
        else:  # cancel
            self.download_finished(download_item, 'aborted')  # Mark as aborted and move to finished tab

        self._process_queue()  # Try to start next available download

    def _generate_unique_filename(self, base_name, is_mp3):
        """Generates a unique filename by appending (n) if a file exists."""
        downloads_path = os.path.join(os.getcwd(), DOWNLOADS_DIR)
        ext = ".mp3" if is_mp3 else ".mp4"

        test_filename = base_name
        counter = 1
        while os.path.exists(os.path.join(downloads_path, test_filename + ext)):
            test_filename = f"{base_name} ({counter})"
            counter += 1
        return test_filename

    def download_finished(self, item_obj, final_status):
        """Callback from DownloadItem when it finishes (success, fail, abort)."""
        if item_obj in self.active_downloads:
            self.active_downloads.remove(item_obj)
            self.completed_downloads_count += 1

        # Update item's status and date_completed for history
        item_obj.status = final_status
        # Updated date format to MM|DD|YYYY - H:MMpm
        item_obj.date_completed = time.strftime("%m|%d|%Y - %I:%M%p")

        # Calculate and store final elapsed time
        if item_obj.start_time:
            item_obj.elapsed_time_seconds = time.time() - item_obj.start_time
        else:
            item_obj.elapsed_time_seconds = 0  # Fallback if start_time wasn't set

        # Save to local history (now inserts at the beginning for newest-on-top)
        self._add_to_local_history(item_obj)

        # Move UI to finished tab - needs to be recreated for ordering
        # First, destroy existing widgets in finished downloads frame to redraw in new order
        for widget in self.finished_downloads_frame_inner.winfo_children():
            widget.destroy()

        # Re-populate finished tab UI from the sorted finished_downloads_data
        # This ensures that when new items are added, or history is loaded,
        # they are correctly displayed with the newest at the top.
        for item_data in self.finished_downloads_data:
            item_obj_for_display = DownloadItem(self.finished_downloads_frame_inner, self, item_data,
                                                is_active_tab=False)
            # Ensure the status is set correctly for history items
            item_obj_for_display.update_status(item_data['status'],
                                               item_obj_for_display._get_status_color(item_data['status']))

        self.finished_downloads_frame_inner.update_idletasks()
        self.finished_canvas.yview_moveto(1.0)  # Scroll to new item (which is now at top visually)

        self._update_queue_control_buttons()
        # Immediately re-process queue to kick off next downloads if available
        self._process_queue()

    def _add_to_local_history(self, item_obj):
        """Adds a finished download item to the local history list and saves to file."""
        history_entry = {
            'id': item_obj.item_id,  # Keep ID for internal tracking
            'url': item_obj.url,
            'video_title': item_obj.video_title,
            'filename': item_obj.filename,  # Store the final filename
            'date_completed': item_obj.date_completed,
            'status': item_obj.status,  # Save final status
            'date_added': item_obj.date_added,  # Store date added
            'filename_provided_by_user': item_obj.filename_provided_by_user,  # Store this flag
            'elapsed_time_seconds': item_obj.elapsed_time_seconds  # Store elapsed time
        }
        self.finished_downloads_data.insert(0, history_entry)  # Insert at beginning for newest-on-top
        self._save_downloads_to_local_history()

    def _load_downloads_from_local_history(self):
        """Loads download history from a local JSON file."""
        if not os.path.exists(HISTORY_FILE):
            self.finished_downloads_data = []
            return

        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                self.finished_downloads_data = json.load(f)

            # Recreate widgets for the finished tab in correct order (newest first)
            for item_data in self.finished_downloads_data:
                # For items loaded from history, they are inherently "finished"
                item_obj = DownloadItem(self.finished_downloads_frame_inner, self, item_data, is_active_tab=False)
                self.download_items_map[item_obj.item_id] = item_obj  # Add to overall map

            self.finished_downloads_frame_inner.update_idletasks()
            self.finished_canvas.config(scrollregion=self.finished_canvas.bbox("all"))
            self._set_status(f"Loaded {len(self.finished_downloads_data)} finished downloads from history.",
                             COLOR_STATUS_READY)

        except json.JSONDecodeError as e:
            messagebox.showwarning("History Load Error", f"Could not read download history (corrupted JSON?): {e}")
            self.finished_downloads_data = []
        except Exception as e:
            messagebox.showerror("History Load Error", f"An error occurred loading history: {e}")
            self.finished_downloads_data = []

    def _save_downloads_to_local_history(self):
        """Saves the current finished downloads list to a local JSON file."""
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.finished_downloads_data, f, indent=4)
        except Exception as e:
            messagebox.showerror("History Save Error", f"Failed to save download history: {e}")

    def remove_from_queue(self, item_obj):
        """Removes a pending download item from the queue if aborted before starting."""
        if item_obj in self.queued_downloads:
            self.queued_downloads.remove(item_obj)
            self.download_finished(item_obj, 'aborted')  # Mark as aborted and move to finished tab

        self._update_queue_control_buttons()

    def _clear_queue(self):
        """Clears all pending downloads from the queue and resets the UI."""
        # Check if there are any downloads at all (active or queued)
        if not self.active_downloads and not self.queued_downloads:
            messagebox.showinfo("Clear Queue", "The download queue is already empty.")
            return

        # Ask for confirmation only if there are any downloads to clear
        if not messagebox.askyesno("Clear Queue",
                                   "Are you sure you want to clear the entire download queue (including active and pending downloads)?"):
            return

        # Abort active downloads first
        for item in list(self.active_downloads):  # Iterate over a copy because the list will be modified
            item.abort_download()  # This will call download_finished to move them to history

        # Cancel queued downloads (not yet active)
        # Iterate over a copy and remove from original list inside loop
        for item in list(self.queued_downloads):
            item.frame.destroy()  # Remove its UI from the active downloads frame
            if item.item_id in self.download_items_map:
                del self.download_items_map[item.item_id]
            self.download_finished(item, 'cancelled')  # Mark as cancelled and move to history

        self.queued_downloads.clear()  # Ensure the internal queue list is empty

        self.total_downloads_added = 0
        self.completed_downloads_count = 0
        self.is_queue_processing_active = False  # Reset this explicitly after clearing
        self.all_downloads_completed.set()  # Set the flag as queue is now clear

        self._set_status("Queue cleared. All active/queued downloads aborted/cancelled.", COLOR_STATUS_ABORTED)
        self._update_queue_control_buttons()
        self.active_downloads_frame_inner.update_idletasks()
        self.active_canvas.config(scrollregion=self.active_canvas.bbox("all"))

    def _clear_finished_history(self):
        """Clears all items from the finished downloads history."""
        if not self.finished_downloads_data and not self.finished_downloads_frame_inner.winfo_children():
            messagebox.showinfo("Clear History", "Finished downloads history is already empty.")
            return

        if messagebox.askyesno("Clear History",
                               "Are you sure you want to clear ALL finished download history? This cannot be undone."):
            # Explicitly destroy all child widgets in the finished downloads frame
            for widget in self.finished_downloads_frame_inner.winfo_children():
                widget.destroy()

            # Clear the in-memory list and the overall map
            self.finished_downloads_data.clear()

            # Rebuild download_items_map to only contain active items, if any
            # This is safer than selectively deleting from a map while iterating,
            # especially since we just destroyed all finished widgets.
            temp_map = {}
            for item_id, item_obj in self.download_items_map.items():
                if item_obj.is_active_tab:
                    temp_map[item_id] = item_obj
            self.download_items_map = temp_map

            self._save_downloads_to_local_history()  # Save empty list to file

            self.finished_downloads_frame_inner.update_idletasks()
            self.finished_canvas.config(scrollregion=self.finished_canvas.bbox("all"))
            self._set_status("Finished downloads history cleared.", COLOR_STATUS_READY)
            messagebox.showinfo("History Cleared", "All finished download history has been cleared.")

    def _update_queue_control_buttons(self, event=None):
        """Enables/disables queue control buttons based on queue/active status."""
        # The start queue button no longer exists, so this only affects clear button
        clear_enabled = bool(self.queued_downloads) or bool(self.active_downloads)

        self.clear_queue_button.config(state="normal" if clear_enabled else "disabled")

    def _show_overall_completion_alert(self):
        """Shows a single alert when all downloads are finished."""
        messagebox.showinfo("All Downloads Complete", "All items in the queue have finished downloading!")
        pass


if __name__ == "__main__":
    root = tk.Tk()
    app = YTDLPGUIApp(root)
    root.mainloop()
