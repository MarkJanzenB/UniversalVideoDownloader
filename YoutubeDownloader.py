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
        self.filename = item_data.get('filename')  # Resolved filename or original proposed
        self.mp3_conversion = item_data.get('mp3_conversion', False)  # Not always needed for history display
        self.source = item_data.get('source', 'N/A')
        self.referer = item_data.get('referer', '')
        self.video_title = item_data.get('video_title', 'Fetching Title...')
        self.status = item_data.get('status',
                                    'queued')  # "queued", "active", "completed", "failed", "aborted", "cancelled"
        self.date_added = item_data.get('date_added', 'N/A')  # New: Date added
        self.date_completed = item_data.get('date_completed', 'N/A')  # Only for finished items
        # New: Track if filename was provided by user or auto-generated
        self.filename_provided_by_user = item_data.get('filename_provided_by_user', False)
        # New: Elapsed time in seconds for history
        self.elapsed_time_seconds = item_data.get('elapsed_time_seconds', 0)

        # Flag to indicate if the video title has been successfully fetched
        self.is_title_fetched = self.filename_provided_by_user or (self.video_title != 'Fetching Title...')

        self.process = None
        self.output_queue = queue.Queue()
        self.start_time = None  # For live elapsed time tracking
        self.last_update_time = None  # For live elapsed time display on active downloads
        self.is_aborted = False
        self.is_merging = False  # Flag to track merging/conversion phase
        # This flag now determines the *layout* of the item, not its tab parent
        self.is_active_item = is_active_item

        self.frame = None  # Will be created in _build_frame_widgets

        # Removed direct calls to update_status and _update_title_label here.
        # These will be called by _refresh_display_order after widgets are built.

        # For new items (added via UI), fetch title. For loaded history, title is already there.
        if self.is_active_item and not self.filename_provided_by_user and not self.is_title_fetched:
            self.fetch_title_async()

    def _build_frame_widgets(self):
        """Builds or rebuilds the UI elements for this individual download item."""
        # Destroy existing frame if it exists and needs to be rebuilt
        if self.frame and self.frame.winfo_exists():
            self.frame.destroy()

        self.frame = tk.Frame(self.parent_frame, bd=2, relief=tk.GROOVE, padx=5, pady=5, bg="#f0f0f0")
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=0)
        self.frame.columnconfigure(2, weight=0)
        self.frame.columnconfigure(3, weight=0)

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

        # Active Item Specific Widgets
        self.progress_bar = ttk.Progressbar(self.frame, orient="horizontal", mode="determinate")
        self.abort_button = tk.Button(self.frame, text="Abort", command=self.abort_download, bg=COLOR_ABORT_BUTTON,
                                      fg="white", font=SMALL_FONT)

        # Finished Item Specific Widgets
        self.open_file_button = tk.Button(self.frame, text="Open File", command=self._open_file_location,
                                          bg=COLOR_OPEN_FILE_BUTTON, fg="white", font=SMALL_FONT)

        if self.is_active_item:
            # Active Item Layout
            self.title_label.grid(row=0, column=0, sticky="nw", padx=2, pady=0)
            self.date_added_label.grid(row=0, column=1, sticky="ne", padx=2, pady=0)
            self.progress_bar.grid(row=1, column=0, sticky="ew", padx=2, pady=0)
            self.status_label.grid(row=1, column=1, sticky="w", padx=2, pady=0)
            self.elapsed_time_label.grid(row=1, column=2, sticky="e", padx=2, pady=0)
            self.abort_button.grid(row=1, column=3, sticky="e", padx=2, pady=0)

            # Ensure finished-item-only widgets are not displayed
            self.url_label.grid_forget()
            self.date_completed_label.grid_forget()
            self.open_file_button.grid_forget()
        else:  # This item is a finished item (completed, failed, aborted, cancelled)
            # Finished Item Layout
            self.title_label.grid(row=0, column=0, columnspan=4, sticky="nw", padx=2, pady=0)
            self.url_label.grid(row=1, column=0, columnspan=4, sticky="nw", padx=2, pady=0)
            self.status_label.grid(row=2, column=0, sticky="w", padx=2, pady=0)
            self.date_added_label.grid(row=2, column=1, sticky="w", padx=2, pady=0)
            self.date_completed_label.grid(row=2, column=2, sticky="e", padx=2, pady=0)
            self.elapsed_time_label.grid(row=2, column=2, sticky="w", padx=2, pady=0)
            self.open_file_button.grid(row=2, column=3, sticky="e", padx=2, pady=0)

            # Ensure active-item-only widgets are not displayed
            self.progress_bar.grid_forget()
            self.abort_button.grid_forget()

            # Set progress bar to 100% for completed, 0% for others in history
            if self.status == 'completed':
                self.progress_bar.config(value=100, mode="determinate")
            else:
                self.progress_bar.config(value=0, mode="determinate")
            # For finished items, ensure abort button is disabled (should already be hidden anyway)
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
        return "black"  # Default color

    def _format_seconds_to_dd_hh_mm_ss(self, total_seconds):
        """
        Formats total seconds into DD|HH|MM or HH|MM|SS.
        If total_seconds >= 1 day, returns DD|HH|MM.
        Else, returns HH|MM|SS.
        """
        if total_seconds < 0:
            total_seconds = 0

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

                # If filename was NOT explicitly set by user, update it with the fetched title
                if not self.filename_provided_by_user:
                    sanitized_title = re.sub(r'[\\/:*?"<>|]', '', self.video_title)
                    self.filename = sanitized_title

                self.is_title_fetched = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)  # Refresh entire display

            except FileNotFoundError:
                self.video_title = "Error: yt-dlp.exe not found."
                if not self.filename_provided_by_user:
                    self.filename = self.url.split('/')[-1].split('?')[0][:50]
                self.is_title_fetched = False
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"FileNotFoundError: yt-dlp.exe not found or not in PATH for URL: {self.url}")
            except subprocess.CalledProcessError as e:
                self.video_title = f"Error fetching title: Command failed. {e.stderr.strip()}"
                if not self.filename_provided_by_user:
                    self.filename = self.url.split('/')[-1].split('?')[0][:50]
                self.is_title_fetched = False
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"subprocess.CalledProcessError for URL {self.url}: {e.stderr.strip()}")
            except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
                self.video_title = f"Error fetching title: {e}"
                if not self.filename_provided_by_user:
                    self.filename = self.url.split('/')[-1].split('?')[0][:50]
                self.is_title_fetched = False
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"Decoding/Timeout Error for URL {self.url}: {e}")
            except Exception as e:
                self.video_title = f"Unexpected error fetching title: {e}"
                if not self.filename_provided_by_user:
                    self.filename = self.url.split('/')[-1].split('?')[0][:50]
                self.is_title_fetched = False
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"General Error fetching title for URL {self.url}: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_title_label(self):
        """Updates the title label on the UI with the fetched title."""
        display_name = self.video_title if self.video_title and self.video_title != 'Fetching Title...' else (
            os.path.basename(self.filename) if self.filename else self.url)
        if len(display_name) > 60:
            display_name = display_name[:57] + "..."

        # Labels are dynamically configured by _build_frame_widgets based on is_active_item
        # This function just updates the text content of the labels that are currently visible
        # Ensure the widget exists before trying to configure it
        if self.title_label.winfo_exists():
            self.title_label.config(text=f"{display_name} ({self.source})")
        if self.date_added_label.winfo_exists():
            self.date_added_label.config(text=f"Added: {self.date_added}")

        if not self.is_active_item:
            display_url = self.url
            if len(display_url) > 70:
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
        self.start_time = time.time()  # Record start time
        self.last_update_time = time.time()  # Reset last update time for live display
        self.update_status("active", COLOR_STATUS_PROGRESS)
        # Re-build and re-pack to ensure active item layout
        self.is_active_item = True
        self.app_instance._refresh_display_order()

        # Check if button and progress bar exist before configuring
        if self.abort_button.winfo_exists():
            self.abort_button.config(state="normal")
        if self.progress_bar.winfo_exists():
            self.progress_bar.config(value=0)
            self.progress_bar.config(mode="determinate")

        # Initial elapsed time display for active downloads
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
        command += ["--paths", f"temp:{temp_dir}"]

        out_name = self.filename

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
                    # Only update elapsed_time_label if it's still mapped to the screen (active item)
                    if self.elapsed_time_label.winfo_exists() and self.elapsed_time_label.winfo_ismapped():
                        self.app_instance.master.after(0, lambda e=elapsed: self.elapsed_time_label.config(
                            text=f"Time: {self._format_seconds_to_dd_hh_mm_ss(e)}"))

            rc = self.process.wait()
            # Stop indeterminate progress bar if it was running
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
            if self.abort_button.winfo_exists():  # Check if button exists before trying to configure
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
        # Ensure the widget exists before trying to configure it
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

        self._create_widgets()  # This will now create the single combined view
        self._initialize_download_management()
        self._load_downloads_from_local_history()

        self.master.after(100, self._process_queue_loop)
        self.on_source_change(YOUTUBE_SOURCE)

        # Log Window variables
        self.log_window = None
        self.log_text = None
        self.log_window_visible = False

    def _setup_window(self, master):
        master.title("YouTube Downloader powered by yt-dlp")
        master.geometry("800x650")
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
        self.url_entry.bind("<Return>", self._add_to_queue_on_enter)
        self.url_entry.bind("<FocusOut>", self._on_url_focus_out)

        # Fixed row index for quality controls
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

        # --- Control Buttons Section ---
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

        # --- Combined Downloads Display Area ---
        # Create a frame to hold the canvas and scrollbar using grid
        self.display_area_frame = tk.Frame(self.main_frame)
        self.display_area_frame.pack(fill="both", expand=True, pady=5)
        self.display_area_frame.grid_rowconfigure(0, weight=1)
        self.display_area_frame.grid_columnconfigure(0, weight=1)  # Canvas column, takes available space
        self.display_area_frame.grid_columnconfigure(1, weight=0)  # Scrollbar column, takes minimum space

        self.downloads_canvas = tk.Canvas(self.display_area_frame, bg="white", highlightthickness=0)
        self.downloads_canvas.grid(row=0, column=0, sticky="nsew")  # Canvas fills its grid cell

        self.downloads_scroll_y = tk.Scrollbar(self.display_area_frame, orient="vertical",
                                               command=self.downloads_canvas.yview)
        self.downloads_scroll_y.grid(row=0, column=1, sticky="ns")  # Scrollbar next to canvas

        self.downloads_canvas.config(yscrollcommand=self.downloads_scroll_y.set)

        self.downloads_frame_inner = tk.Frame(self.downloads_canvas, bg="white")
        # Set initial width to 0, it will be immediately updated by _on_downloads_canvas_resize
        self.downloads_canvas_window_id = self.downloads_canvas.create_window((0, 0), window=self.downloads_frame_inner,
                                                                              anchor="nw", width=0)

        self.downloads_frame_inner.bind("<Configure>", lambda e: self.downloads_canvas.configure(
            scrollregion=self.downloads_canvas.bbox("all")))
        self.downloads_canvas.bind('<Configure>', self._on_downloads_canvas_resize)
        # Added mouse wheel scrolling for the combined downloads display
        self.downloads_canvas.bind('<MouseWheel>', self._on_mousewheel)
        self.downloads_canvas.bind('<Button-4>', self._on_mousewheel)
        self.downloads_canvas.bind('<Button-5>', self._on_mousewheel)

        # --- Status Bar ---
        self.status_bar = tk.Label(self.master, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W, font=SMALL_FONT,
                                   fg=COLOR_STATUS_READY)
        self.status_bar.pack(side="bottom", fill="x")

    def _on_mousewheel(self, event):
        """Handles mouse wheel scrolling for the combined downloads canvas."""
        self.downloads_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"  # Prevent event propagation

    def _on_downloads_canvas_resize(self, event):
        """Adjusts the width of the inner frame when the canvas resizes."""
        # event.width now refers to the total width of the canvas, which is the usable width for the inner frame
        self.downloads_canvas.itemconfig(self.downloads_canvas_window_id, width=event.width)
        self.downloads_canvas.configure(scrollregion=self.downloads_canvas.bbox("all"))

    def _initialize_download_management(self):
        self.queued_downloads = []  # List of DownloadItem objects (waiting to start)
        self.active_downloads = []  # List of DownloadItem objects (currently downloading)
        self.download_items_map = {}  # {item_id: DownloadItem object} for easy lookup of all items (active and finished)

        self.finished_downloads_data = []  # List of dictionaries for finished downloads history (used for saving/loading)

        self.download_item_counter = 0
        self.completed_downloads_count = 0
        self.total_downloads_added = 0
        self.is_queue_processing_active = False

        self.all_downloads_completed = threading.Event()
        self.alert_on_completion_for_session = False  # New flag to control session-based alerts

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
                [], [], [],
                [("1080", "High Quality - 1080p")],
                [("720", "Medium Quality - 720p")],
                [("480", "Low Quality - 480p")]
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
        filename_input = self.filename_entry.get().strip()

        filename_provided_by_user = bool(filename_input)
        filename = filename_input if filename_provided_by_user else url.split('/')[-1].split('?')[0][:50]

        mp3_conversion = self.mp3_var.get()
        referer = self.referer_entry.get().strip() if source == XTREAM_SOURCE else ""

        self.download_item_counter += 1
        item_id = f"dl_{self.download_item_counter}_{int(time.time())}"
        current_time_str = time.strftime("%m|%d|%Y - %I:%M%p")

        new_download_data = {
            'id': item_id,
            'url': url,
            'quality': quality,
            'filename': filename,
            'mp3_conversion': mp3_conversion,
            'source': source,
            'referer': referer,
            'status': 'queued',
            'video_title': 'Fetching Title...',
            'date_added': current_time_str,
            'filename_provided_by_user': filename_provided_by_user,
            'elapsed_time_seconds': 0
        }

        new_item = DownloadItem(self, new_download_data, is_active_item=True)  # Always active initially
        self.queued_downloads.append(new_item)
        self.download_items_map[new_item.item_id] = new_item  # Add to overall map of all items
        self.total_downloads_added += 1

        self._set_status(f"Added '{url[:40]}...' to queue. Queue size: {len(self.queued_downloads)}",
                         COLOR_STATUS_READY)
        self._update_queue_control_buttons()

        # Set flag for session-based completion alert and clear event
        self.alert_on_completion_for_session = True
        self.all_downloads_completed.clear()

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

        self._refresh_display_order()  # Refresh to show new queued item
        self.downloads_canvas.yview_moveto(1.0)  # Scroll to new item

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
        self.quality_var.set("Fetching qualities...")

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

    def _process_queue_loop(self):
        """Main loop for polling individual download item queues and managing concurrency."""
        # Loop through active downloads to update their UI elements like elapsed time.
        for item in list(self.active_downloads):
            try:
                while True:
                    _ = item.output_queue.get_nowait()
            except queue.Empty:
                pass

            if item.start_time:  # Only update if download has started
                elapsed = time.time() - item.start_time
                # Only update elapsed_time_label if it's still mapped to the screen (active item)
                if item.elapsed_time_label.winfo_exists() and item.elapsed_time_label.winfo_ismapped():
                    item.elapsed_time_label.config(text=f"Time: {item._format_seconds_to_dd_hh_mm_ss(elapsed)}")

        # Keep processing queue if there are items or active downloads
        if self.queued_downloads or self.active_downloads:
            self.is_queue_processing_active = True
            self._process_queue()
        else:
            self.is_queue_processing_active = False
            # Only update status bar to "Ready" if nothing is pending and no completion alert is due
            if self.status_bar.cget("text") != "All downloads complete!":
                self._set_status("Ready", COLOR_STATUS_READY)

        self.master.after(100, self._process_queue_loop)

    def _process_queue(self):
        """
        Checks for available slots, handles file conflicts, and starts downloads from the queue.
        This method is called repeatedly by the main loop.
        """
        self.is_queue_processing_active = True

        # Iterate over a copy of queued_downloads so we can modify the original list
        for i, next_item in enumerate(list(self.queued_downloads)):
            if len(self.active_downloads) >= MAX_CONCURRENT_DOWNLOADS:
                break

                # Only process items where filename is explicitly provided OR title has been fetched
            if not next_item.filename_provided_by_user and not next_item.is_title_fetched:
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
                return
            else:
                # No conflict, proceed with download
                self.queued_downloads.remove(next_item)
                self.active_downloads.append(next_item)
                next_item.start_download()  # This will call _refresh_display_order
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
        dialog.transient(self.master)
        dialog.grab_set()
        dialog.resizable(False, False)

        filename_display = os.path.basename(existing_filepath)

        tk.Label(dialog, text=f"The file '{filename_display}' already exists.\nWhat would you like to do?",
                 font=MAIN_FONT, wraplength=300, justify="center", padx=10, pady=10).pack()

        button_frame = tk.Frame(dialog, padx=10, pady=5)
        button_frame.pack()

        result = tk.StringVar(value="")

        def on_choice(choice):
            result.set(choice)
            dialog.destroy()

        tk.Button(button_frame, text="Overwrite", bg=COLOR_ABORT_BUTTON, fg="white", font=BOLD_FONT,
                  command=lambda: on_choice("overwrite")).pack(side="left", padx=5, pady=5)
        tk.Button(button_frame, text="Keep Both", bg=COLOR_ADD_BUTTON, fg="white", font=BOLD_FONT,
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
            download_item.filename = new_filename

            self.active_downloads.append(download_item)
            download_item.start_download()
            self._set_status(f"Starting download (renamed to '{new_filename}'). Active: {len(self.active_downloads)}",
                             COLOR_STATUS_PROGRESS)
        else:  # cancel
            self.download_finished(download_item, 'aborted')

        self._process_queue()

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

        item_obj.status = final_status
        item_obj.date_completed = time.strftime("%m|%d|%Y - %I:%M%p")
        if item_obj.start_time:
            item_obj.elapsed_time_seconds = time.time() - item_obj.start_time
        else:
            item_obj.elapsed_time_seconds = 0

            # Mark as not an active item anymore
        item_obj.is_active_item = False

        # Add to local history (inserts at the beginning for newest-on-top)
        self._add_to_local_history(item_obj)

        # Refresh the entire display to re-sort all items
        self._refresh_display_order()

        self._update_queue_control_buttons()
        self._process_queue()

        # Check if all downloads for this session are complete and alert is due
        if not self.active_downloads and not self.queued_downloads:
            if self.alert_on_completion_for_session and not self.all_downloads_completed.is_set():
                self.all_downloads_completed.set()
                self._show_overall_completion_alert()
                self.alert_on_completion_for_session = False  # Reset for next batch of downloads

    def _add_to_local_history(self, item_obj):
        """Adds a finished download item to the local history list and saves to file."""
        history_entry = {
            'id': item_obj.item_id,
            'url': item_obj.url,
            'video_title': item_obj.video_title,
            'filename': item_obj.filename,
            'date_completed': item_obj.date_completed,
            'status': item_obj.status,
            'date_added': item_obj.date_added,
            'filename_provided_by_user': item_obj.filename_provided_by_user,
            'elapsed_time_seconds': item_obj.elapsed_time_seconds
        }
        self.finished_downloads_data.insert(0, history_entry)
        self._save_downloads_to_local_history()

    def _load_downloads_from_local_history(self):
        """Loads download history from a local JSON file."""
        if not os.path.exists(HISTORY_FILE):
            self.finished_downloads_data = []
            return

        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                # Ensure each loaded item is instantiated as DownloadItem and added to the map
                for item_data in loaded_data:
                    item_obj = DownloadItem(self, item_data,
                                            is_active_item=False)  # These are historical, so not active
                    self.download_items_map[item_obj.item_id] = item_obj
                self.finished_downloads_data = loaded_data  # Keep raw data for saving

            self._refresh_display_order()  # Populate display
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
            self.download_finished(item_obj, 'aborted')

        self._update_queue_control_buttons()

    def _clear_queue(self):
        """Clears all pending downloads from the queue and resets the UI."""
        if not self.active_downloads and not self.queued_downloads:
            messagebox.showinfo("Clear Queue", "The download queue is already empty.")
            return

        if not messagebox.askyesno("Clear Queue",
                                   "Are you sure you want to clear the entire download queue (including active and pending downloads)?"):
            return

        # Abort active downloads first
        for item in list(self.active_downloads):
            item.abort_download()

            # Cancel queued downloads (not yet active)
        for item in list(self.queued_downloads):
            # No process to kill for queued items, just mark as cancelled
            if item.item_id in self.download_items_map:
                # Ensure the item is properly moved to history with cancelled status
                self.download_finished(item, 'cancelled')

        self.queued_downloads.clear()

        self.total_downloads_added = 0
        self.completed_downloads_count = 0
        self.is_queue_processing_active = False
        self.all_downloads_completed.set()
        self.alert_on_completion_for_session = False  # No alert after clearing

        self._set_status("Queue cleared. All active/queued downloads aborted/cancelled.", COLOR_STATUS_ABORTED)
        self._update_queue_control_buttons()
        self._refresh_display_order()  # Refresh display to remove cancelled items

    def _clear_finished_history(self):
        """Clears all items from the finished downloads history."""
        if not self.finished_downloads_data and not self.downloads_frame_inner.winfo_children():
            messagebox.showinfo("Clear History", "Finished downloads history is already empty.")
            return

        if messagebox.askyesno("Clear History",
                               "Are you sure you want to clear ALL finished download history? This cannot be undone."):
            # Clear the in-memory list
            self.finished_downloads_data.clear()

            # Remove finished items from the overall map
            keys_to_remove = [item_id for item_id, item_obj in self.download_items_map.items() if
                              not item_obj.is_active_item]
            for key in keys_to_remove:
                del self.download_items_map[key]

            self._save_downloads_to_local_history()  # Save empty list to file
            self._refresh_display_order()  # Refresh display to remove history items

            self._set_status("Finished downloads history cleared.", COLOR_STATUS_READY)
            messagebox.showinfo("History Cleared", "All finished download history has been cleared.")

    def _update_queue_control_buttons(self, event=None):
        """Enables/disables queue control buttons based on queue/active status."""
        clear_enabled = bool(self.queued_downloads) or bool(self.active_downloads)

        self.clear_queue_button.config(state="normal" if clear_enabled else "disabled")

    def _show_overall_completion_alert(self):
        """Shows a single alert when all downloads are finished."""
        messagebox.showinfo("All Downloads Complete", "All items in the queue have finished downloading!")
        pass

    def _refresh_display_order(self):
        """Refreshes the display of all download items based on their status and order."""
        # 1. Destroy existing widgets in the display frame
        for widget in self.downloads_frame_inner.winfo_children():
            widget.destroy()

        # 2. Prepare all items for display
        all_display_items = []
        # Add active items
        for item_obj in self.active_downloads:
            all_display_items.append(item_obj)
        # Add queued items
        for item_obj in self.queued_downloads:
            all_display_items.append(item_obj)

        # Add finished/aborted/cancelled items (from history data)
        # Re-instantiate DownloadItem objects from history data to ensure fresh UI elements
        # (This avoids issues if a DownloadItem object was destroyed from an old parent frame
        # but its data still exists in finished_downloads_data)
        for item_data in self.finished_downloads_data:
            # Retrieve the existing DownloadItem object if it's already in the map,
            # otherwise create a new one (e.g., if loaded from history file for first time).
            # This is to ensure we don't duplicate DownloadItem objects if they are already active/queued.
            if item_data['id'] not in self.download_items_map:
                # This case should ideally not happen if download_items_map always holds all
                # items, but as a safeguard.
                item_obj = DownloadItem(self, item_data, is_active_item=False)
                self.download_items_map[item_obj.item_id] = item_obj
            else:
                item_obj = self.download_items_map[item_data['id']]
                item_obj.is_active_item = False  # Ensure it's marked as non-active for display purposes
            all_display_items.append(item_obj)

        # 3. Sort items for display: Active first, then finished (newest first)
        def sort_key(item):
            # Active items (True for is_active_item) come first (False for reverse sorting)
            active_sort = not item.is_active_item

            # For finished items, sort by date_completed descending (newest first)
            # Use a safe default for date conversion if date_completed is not available or "N/A"
            if not item.is_active_item and item.date_completed != 'N/A':
                try:
                    # Convert "MM|DD|YYYY - H:MMpm" to a comparable timestamp
                    date_obj = time.strptime(item.date_completed, "%m|%d|%Y - %I:%M%p")
                    time_sort = -time.mktime(date_obj)  # Negative for descending order (newest first)
                except ValueError:
                    time_sort = -time.time()  # Fallback to current time if date format is unexpected
            else:
                time_sort = -time.time()  # Active/queued items: no date_completed, use current time (will be overridden by active_sort)

            return (active_sort, time_sort)

        all_display_items.sort(key=sort_key)

        # 4. Pack items into the display frame
        for item_obj in all_display_items:
            item_obj.parent_frame = self.downloads_frame_inner  # Set the current parent frame
            item_obj._build_frame_widgets()  # Build/rebuild its widgets
            item_obj.frame.pack(fill="x", padx=5, pady=3)  # Pack the frame into the inner frame
            item_obj._update_title_label()  # Ensure labels are correctly updated after packing
            item_obj.update_status(item_obj.status, item_obj._get_status_color(item_obj.status))

        # 5. Update canvas scroll region
        self.downloads_frame_inner.update_idletasks()
        self.downloads_canvas.config(scrollregion=self.downloads_canvas.bbox("all"))


if __name__ == "__main__":
    root = tk.Tk()
    app = YTDLPGUIApp(root)
    root.mainloop()
