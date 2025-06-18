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
                                        timeout=30)
                metadata = json.loads(result.stdout)
                self.video_title = metadata.get('title', 'Unknown Title')

                # If filename was NOT explicitly set by user, update it with the fetched title
                if not self.filename_provided_by_user:
                    sanitized_title = re.sub(r'[\\/:*?"<>|]', '', self.video_title)
                    self.filename = sanitized_title if sanitized_title else f"VideoPlayback_{self.item_id}"  # Fallback to generic name

                self.is_title_fetched = True
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)  # Refresh entire display

            except FileNotFoundError:
                self.video_title = "Error: yt-dlp.exe not found."
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"  # Fallback to generic name
                self.is_title_fetched = False
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"FileNotFoundError: yt-dlp.exe not found or not in PATH for URL: {self.url}")
            except subprocess.CalledProcessError as e:
                self.video_title = f"Error fetching title: Command failed. {e.stderr.strip()}"
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"  # Fallback to generic name
                self.is_title_fetched = False
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"subprocess.CalledProcessError for URL {self.url}: {e.stderr.strip()}")
            except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
                self.video_title = f"Error fetching title: {e}"
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"  # Fallback to generic name
                self.is_title_fetched = False
                self.app_instance.master.after(0, self.app_instance._refresh_display_order)
                self.app_instance.master.after(0, lambda: self.update_status("Error", COLOR_STATUS_FAILED))
                print(f"Decoding/Timeout Error for URL {self.url}: {e}")
            except Exception as e:
                self.video_title = f"Unexpected error fetching title: {e}"
                if not self.filename_provided_by_user:
                    self.filename = f"VideoPlayback_{self.item_id}"  # Fallback to generic name
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

        out_name = self.filename  # This is now guaranteed to be a string due to __init__ changes

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
        self._cleanup_temp_directories_on_launch()  # Call cleanup function on launch
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
                                              command=self._clear_finished_history, bg=COLOR_CLEAR_BUTTON,
                                              fg="black", font=BOLD_FONT)
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
        filename_input = self.filename_entry.get().strip()  # Get user-provided filename

        filename_provided_by_user = bool(filename_input)

        # Determine the filename to use. Always ensure it's a string.
        filename_for_item_data = ""  # Initialize to empty string
        if filename_input:
            filename_for_item_data = filename_input
        else:
            # First, try to use the fetched video title if available and meaningful
            # For YouTube, the video_title is fetched asynchronously. When adding to queue,
            # it might still be 'Fetching Title...'. So, use it only if it's already fetched.
            # This logic needs to consider that the DownloadItem itself will handle fetching the title.
            # For now, we'll use a generic fallback. The DownloadItem's fetch_title_async will update
            # its own filename if filename_provided_by_user is False.

            # For initial queuing, use a generic placeholder. The DownloadItem will update it.
            filename_for_item_data = f"VideoPlayback_{self.download_item_counter}"
            # This ensures that `filename` is always a string from the moment `DownloadItem` is created.

        mp3_conversion = self.mp3_var.get()
        referer = self.referer_entry.get().strip() if source == XTREAM_SOURCE else ""

        # Increment counter for unique ID
        self.download_item_counter += 1
        item_id = self.download_item_counter

        item_data = {
            'id': item_id,
            'url': url,
            'quality': quality,
            'filename': filename_for_item_data,  # Now guaranteed to be a string
            'mp3_conversion': mp3_conversion,
            'source': source,
            'referer': referer,
            'video_title': 'Fetching Title...',  # This will be updated by fetch_title_async
            'status': 'queued',
            'date_added': time.strftime("%m|%d|%Y - %I:%M%p"),
            'filename_provided_by_user': filename_provided_by_user,
            'elapsed_time_seconds': 0  # Added this line from original snippet for completeness
        }

        new_item = DownloadItem(self, item_data, is_active_item=True)
        self.queued_downloads.append(new_item)
        self.download_items_map[item_id] = new_item
        self.total_downloads_added += 1
        self._refresh_display_order()  # Refresh display to show the new item
        self._set_status(f"Added '{url}' to queue.", COLOR_STATUS_READY)

        self.url_entry.delete(0, END)
        self.filename_entry.delete(0, END)
        self.mp3_var.set(False)
        self.referer_entry.delete(0, END)
        self.url_entry.focus_set()
        self.alert_on_completion_for_session = True  # Enable alert for this session if any downloads are added

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
                'id': -1,  # Dummy ID
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
            temp_item = DownloadItem(self, temp_item_data, is_active_item=True)

            def _update_filename_after_fetch():
                if not self.filename_entry.get().strip():  # Only update if user hasn't typed anything
                    if temp_item.is_title_fetched and temp_item.video_title != 'Unknown Title' and temp_item.video_title != 'Fetching Title...':
                        sanitized_title = re.sub(r'[\\/:*?"<>|]', '', temp_item.video_title)
                        self.filename_entry.delete(0, END)
                        self.filename_entry.insert(0, sanitized_title[:50])  # Limit length for preview
                    else:
                        # Fallback to generic name if title fetch failed or is still pending
                        self.filename_entry.delete(0, END)
                        self.filename_entry.insert(0, f"VideoPlayback_Preview")  # Generic name for preview

            # Fetch title asynchronously and then update filename_entry
            threading.Thread(
                target=lambda: (temp_item.fetch_title_async(), self.master.after(500, _update_filename_after_fetch)),
                daemon=True).start()

    def _update_quality_options_grouped(self, auto, combined_video_audio, combined_audio_only, video_only,
                                        high_quality_video, medium_quality_video, low_quality_video):
        """Updates the quality OptionMenu with new options based on source."""
        menu = self.quality_menu["menu"]
        menu.delete(0, "end")  # Clear existing options

        def add_command(value):
            menu.add_command(label=value, command=tk._setit(self.quality_var, value))

        # Grouping logic
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

        # Ensure a default is selected if the current one is no longer available
        if self.quality_var.get() not in [item[0] for item in
                                          auto + combined_video_audio + combined_audio_only + video_only + high_quality_video + medium_quality_video + low_quality_video]:
            if auto:
                self.quality_var.set(auto[0][0])
            else:
                self.quality_var.set("Auto (Best available)")  # Fallback

    def _process_queue_loop(self):
        """Manages the download queue, starting new downloads as slots become free."""
        active_count = len(self.active_downloads)
        if self.queued_downloads and active_count < MAX_CONCURRENT_DOWNLOADS:
            next_item = self.queued_downloads.pop(0)
            self.active_downloads.append(next_item)
            next_item.start_download()
            self.is_queue_processing_active = True
            self.all_downloads_completed.clear()  # Clear the event when downloads are active
            self._set_status(f"Starting download for {next_item.video_title}...", COLOR_STATUS_PROGRESS)
        elif not self.active_downloads and not self.queued_downloads and self.is_queue_processing_active:
            # All downloads are finished
            self.is_queue_processing_active = False
            self.all_downloads_completed.set()  # Set the event when all downloads are completed

            if self.alert_on_completion_for_session and self.total_downloads_added > 0:
                messagebox.showinfo("Downloads Complete",
                                    f"All {self.completed_downloads_count} downloads finished!")
                self.alert_on_completion_for_session = False
                self.completed_downloads_count = 0
                self.total_downloads_added = 0
            self._set_status("All downloads finished. Ready.", COLOR_STATUS_COMPLETE)
        self.master.after(1000, self._process_queue_loop)  # Check again after 1 second

    def download_finished(self, item, final_status):
        """Called by a DownloadItem when its download process completes (success/fail/abort)."""
        if item in self.active_downloads:
            self.active_downloads.remove(item)

        item.status = final_status
        item.date_completed = time.strftime("%m|%d|%Y - %I:%M%p")
        if item.start_time:
            item.elapsed_time_seconds = int(time.time() - item.start_time)
        else:
            item.elapsed_time_seconds = 0

        # Move item from active (or queued if it was aborted before starting) to finished display
        # First remove it from download_items_map if it was just a temporary object for queue (shouldn't happen with current flow)
        # Add it to finished_downloads_data (for saving history)
        self.finished_downloads_data.insert(0, self._get_item_data_for_history(item))  # Add to top of history
        self._save_downloads_to_local_history()  # Save after each completion

        # Update counter if completed successfully
        if final_status == "completed":
            self.completed_downloads_count += 1
            self._set_status(f"Download for '{item.video_title}' completed!", COLOR_STATUS_COMPLETE)
        elif final_status == "aborted":
            self._set_status(f"Download for '{item.video_title}' aborted.", COLOR_STATUS_ABORTED)
        else:
            self._set_status(f"Download for '{item.video_title}' failed.", COLOR_STATUS_FAILED)

        # Rebuild/refresh the display to move completed item to history section
        self._refresh_display_order()

    def remove_from_queue(self, item_to_remove):
        """Removes a specified item from the queued_downloads list."""
        if item_to_remove in self.queued_downloads:
            self.queued_downloads.remove(item_to_remove)
            self.download_items_map.pop(item_to_remove.item_id, None)  # Remove from map
            self._refresh_display_order()
            self._set_status(f"Removed '{item_to_remove.video_title}' from queue.", COLOR_STATUS_READY)

    def _clear_queue(self):
        """Clears all items from the active and queued downloads."""
        for item in self.active_downloads[:]:
            item.abort_download()  # Abort any active downloads
        self.queued_downloads.clear()
        self.active_downloads.clear()
        # Remove active items from the map
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
            self.finished_downloads_data.clear()
            # Also remove finished items from the map
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
        # Clear existing widgets from the inner frame
        for widget in self.downloads_frame_inner.winfo_children():
            widget.destroy()

        # 1. Prepare lists of displayable items
        all_display_items = []
        seen_ids = set()

        for item in self.active_downloads:
            if item.item_id not in seen_ids:
                all_display_items.append(item)
                seen_ids.add(item.item_id)
        for item in self.queued_downloads:
            if item.item_id not in seen_ids:
                all_display_items.append(item)
                seen_ids.add(item.item_id)
        for item_data in self.finished_downloads_data:
            if item_data['id'] not in seen_ids:
                item_obj = self.download_items_map.get(item_data['id'])
                if item_obj:
                    item_obj.is_active_item = False
                else:
                    item_obj = DownloadItem(self, item_data, is_active_item=False)
                    self.download_items_map[item_data['id']] = item_obj
                all_display_items.append(item_obj)
                seen_ids.add(item_data['id'])

        # 3. Sort items for display: active/queued first (by date added), then finished (newest completed first)
        def sort_key(item):
            # Active/queued items appear first
            active_sort = 0 if item.is_active_item else 1
            time_sort = 0

            if item.is_active_item:
                try:
                    # Convert "MM|DD|YYYY - H:MMpm" to a comparable timestamp
                    date_obj = time.strptime(item.date_added, "%m|%d|%Y - %I:%M%p")
                    time_sort = -time.mktime(date_obj)  # Negative for descending order (newest first)
                except ValueError:
                    time_sort = -time.time()  # Fallback to current time if date format is unexpected
            elif item.date_completed != 'N/A':
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
        """Saves the current finished_downloads_data to a local JSON file."""
        # Only save finished items
        history_to_save = [
            self._get_item_data_for_history(item)
            for item in self.download_items_map.values()
            if not item.is_active_item
        ]
        history_to_save.sort(key=lambda x: time.mktime(time.strptime(x['date_completed'], "%m|%d|%Y - %I:%M%p")) if x[
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
                    loaded_history = json.load(f)
                    # Initialize download_item_counter to be greater than any loaded ID
                    if loaded_history:
                        self.download_item_counter = max(item['id'] for item in loaded_history) + 1
                    else:
                        self.download_item_counter = 0

                    for item_data in loaded_history:
                        # Ensure loaded items are marked as finished and not active
                        item_data['status'] = item_data.get('status',
                                                            'completed')  # Default to completed if status missing
                        # If a completed item was in active_downloads during a crash, ensure its temp_dir is cleaned up
                        temp_path = os.path.join(os.getcwd(), DOWNLOADS_DIR, TEMP_SUBDIR, str(item_data['id']))
                        if os.path.exists(temp_path):
                            shutil.rmtree(temp_path, ignore_errors=True)

                        history_item = DownloadItem(self, item_data, is_active_item=False)
                        # We are no longer adding to finished_downloads_data directly here,
                        # as _refresh_display_order will re-populate it from self.download_items_map
                        self.download_items_map[item_data['id']] = history_item  # Store object in map

                self._refresh_display_order()  # Display loaded history
            except (IOError, json.JSONDecodeError) as e:
                print(f"Error loading history: {e}")
                messagebox.showwarning("History Load Error",
                                       f"Could not load download history. It might be corrupted or missing: {e}")
        else:
            self.download_item_counter = 0  # Start counter from 0 if no history file

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
