import tkinter as tk
from tkinter import scrolledtext, messagebox, END, ttk
import subprocess
import sys
import os
import threading
import queue
import shutil
import time
import re  # For extracting percentage, speed, and ETA

# --- Constants for consistent naming and values ---
DOWNLOADS_DIR = "downloads"
TEMP_SUBDIR = "temp"
YOUTUBE_SOURCE = "YouTube"
XTREAM_SOURCE = "XtremeStream"
MAX_CONCURRENT_DOWNLOADS = 2

# Colors for buttons/status (Tailwind-like or common vibrant colors)
COLOR_ADD_BUTTON = "#28A745"  # Green
COLOR_ABORT_BUTTON = "#DC3545"  # Red
COLOR_START_QUEUE_BUTTON = "#007BFF"  # Blue
COLOR_CLEAR_BUTTON = "#FFC107"  # Yellow-Orange

COLOR_STATUS_READY = "black"
COLOR_STATUS_PROGRESS = "#007BFF"  # Blue
COLOR_STATUS_COMPLETE = "#28A745"  # Green
COLOR_STATUS_FAILED = "#DC3545"  # Red
COLOR_STATUS_ABORTED = "#FFC107"  # Orange

# Font for better aesthetics
MAIN_FONT = ("Inter", 10)
BOLD_FONT = ("Inter", 12, "bold")
SMALL_FONT = ("Inter", 9)
MONO_FONT = ("Roboto Mono", 9)  # For output box


class DownloadItem:
    """
    Manages the UI and logic for a single download.
    """

    def __init__(self, parent_frame, app_instance, item_id, url, quality, filename, mp3_conversion, source, referer):
        self.parent_frame = parent_frame  # The frame that will contain this item's UI
        self.app_instance = app_instance  # Reference to the main YTDLPGUIApp instance
        self.item_id = item_id  # Unique ID for this download item

        self.url = url
        self.quality = quality
        self.filename = filename
        self.mp3_conversion = mp3_conversion
        self.source = source
        self.referer = referer

        self.process = None  # Holds the subprocess.Popen object
        self.output_queue = queue.Queue()  # Queue for this specific download's stdout/stderr
        self.start_time = None
        self.is_aborted = False  # Flag to indicate if download was aborted by user

        self._create_widgets()

    def _create_widgets(self):
        """Creates the UI elements for this individual download item."""
        self.frame = tk.Frame(self.parent_frame, bd=2, relief=tk.GROOVE, padx=5, pady=5, bg="#f0f0f0")
        self.frame.pack(fill="x", padx=5, pady=3, expand=True)

        # Row 1: URL/Filename Label
        display_name = os.path.basename(self.filename) if self.filename else self.url
        tk.Label(self.frame, text=f"URL: {self.url[:60]}... ({self.source})", font=MAIN_FONT, anchor="w",
                 bg="#f0f0f0").pack(fill="x")
        tk.Label(self.frame, text=f"Output: {display_name}", font=MAIN_FONT, anchor="w", bg="#f0f0f0").pack(fill="x")

        # Row 2: Progress bar
        self.progress_bar = ttk.Progressbar(self.frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill="x", pady=2)

        # Row 3: Status and Abort button
        status_frame = tk.Frame(self.frame, bg="#f0f0f0")
        status_frame.pack(fill="x")

        self.status_label = tk.Label(status_frame, text="Queued", font=SMALL_FONT, anchor="w", bg="#f0f0f0",
                                     fg=COLOR_STATUS_READY)
        self.status_label.pack(side="left", fill="x", expand=True)

        self.abort_button = tk.Button(status_frame, text="Abort", command=self.abort_download, bg=COLOR_ABORT_BUTTON,
                                      fg="white", font=SMALL_FONT)
        self.abort_button.pack(side="right")

    def start_download(self):
        """Starts the yt-dlp process for this item in a new thread."""
        self.is_aborted = False
        self.start_time = time.time()
        self.update_status("Starting...", COLOR_STATUS_PROGRESS)
        self.abort_button.config(state="normal")
        self.progress_bar.config(value=0)

        command = self._build_command()
        threading.Thread(target=self._run_yt_dlp, args=(command,), daemon=True).start()

    def _build_command(self):
        """Builds the yt-dlp command for this specific download item."""
        command = [self.app_instance.yt_dlp_path, self.url]

        # Referer handling
        if self.source == XTREAM_SOURCE and self.referer:
            command += ["--add-header", f"referer: {self.referer}"]

        # Ensure downloads directory exists
        downloads_dir = os.path.join(os.getcwd(), DOWNLOADS_DIR)
        temp_dir = os.path.join(downloads_dir, TEMP_SUBDIR, str(self.item_id))  # Unique temp dir for each download
        os.makedirs(temp_dir, exist_ok=True)
        command += ["--paths", f"temp:{temp_dir}"]

        # Filename and format
        out_name = self.filename or "%(title)s"
        if self.mp3_conversion:
            out_name += ".mp3"
            command += ["--extract-audio", "--audio-format", "mp3"]
        else:
            out_name += ".mp4"
            command += ["--recode-video", "mp4"]  # Using recode-video as per original code

        command += ["--output", os.path.join(downloads_dir, out_name)]

        # Quality for YouTube
        if self.source == YOUTUBE_SOURCE:
            if "1080" in self.quality:
                command += ['-f', 'bestvideo[height>=1080]+bestaudio/best[height<=1080]']
            elif "720" in self.quality:
                command += ['-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]']
            elif "480" in self.quality:
                command += ['-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]']

        # Add a flag to allow yt-dlp to output more structured progress
        command += ["--newline", "--progress"]
        return command

    def _run_yt_dlp(self, command):
        """Runs the yt-dlp subprocess and captures its output."""
        self.output_queue.put(f"Executing: {' '.join(command)}\n")
        rc = -1  # Default return code for errors before execution
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            self.process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                universal_newlines=True, creationflags=creationflags
            )
            for line in self.process.stdout:
                if self.is_aborted:  # Check abort flag while reading output
                    break
                self.output_queue.put(line)
                self._parse_output_for_progress(line)

            rc = self.process.wait()
            if self.is_aborted:
                self.update_status("Aborted", COLOR_STATUS_ABORTED)
            elif rc == 0:
                self.update_status("Complete", COLOR_STATUS_COMPLETE)
                self.progress_bar.config(value=100)
            else:
                self.update_status(f"Failed (Exit {rc})", COLOR_STATUS_FAILED)

        except FileNotFoundError:
            self.update_status("Error: yt-dlp.exe not found.", COLOR_STATUS_FAILED)
            self.output_queue.put(
                "Error: yt-dlp.exe not found. Please ensure it's in the same directory as the app or in your PATH.\n")
        except Exception as e:
            self.update_status(f"Error: {e}", COLOR_STATUS_FAILED)
            self.output_queue.put(f"An unexpected error occurred: {e}\n")
        finally:
            self.process = None  # Clear process reference
            self.abort_button.config(state="disabled")
            # Clean up temp directory
            temp_path = os.path.join(os.getcwd(), DOWNLOADS_DIR, TEMP_SUBDIR, str(self.item_id))
            if os.path.exists(temp_path):
                shutil.rmtree(temp_path, ignore_errors=True)
            # Notify main app that this download is finished
            self.app_instance.download_finished(self.item_id, rc == 0 and not self.is_aborted)

    def _parse_output_for_progress(self, line):
        """Parses a line of yt-dlp output for progress, speed, and ETA."""
        # This regex tries to capture percentage, speed, and ETA from yt-dlp output.
        # Example lines:
        # [download] 12.3% of 123.45MiB at 1.23MiB/s ETA 00:01
        # [download] 12.3% of 123.45MiB at Unknown ETA Unknown
        match = re.search(
            r'\[download\]\s+(\d+\.\d+)%\s+of\s+.*?\s+at\s+([0-9\.]+KiB/s|[0-9\.]+MiB/s|\S+)?(?:\s+ETA\s+(\d{2}:\d{2}))?',
            line)
        if match:
            percent = float(match.group(1))
            speed = match.group(2) if match.group(2) else 'N/A'
            eta = match.group(3) if match.group(3) else 'N/A'

            self.progress_bar.config(value=percent)
            self.update_status(f"Downloading... {percent:.1f}% ({speed}, ETA {eta})", COLOR_STATUS_PROGRESS)
        elif "merging formats" in line.lower() or "ffmpeg" in line.lower():
            self.update_status("Converting...", COLOR_STATUS_PROGRESS)
        elif "downloading" in line.lower():
            self.update_status("Downloading...", COLOR_STATUS_PROGRESS)

    def update_status(self, text, color):
        """Updates the status label for this download item."""
        self.status_label.config(text=text, fg=color)

    def abort_download(self):
        """Aborts the currently running download process."""
        self.is_aborted = True
        if self.process:
            try:
                self.process.kill()
                self.update_status("Aborting...", COLOR_STATUS_ABORTED)  # Update immediately
                self.output_queue.put("\nProcess aborted by user.\n")
            except Exception as e:
                self.output_queue.put(f"Error trying to abort process: {e}\n")
                self.update_status(f"Abort error: {e}", COLOR_STATUS_FAILED)
        else:
            self.update_status("Already stopped/queued.", COLOR_STATUS_ABORTED)
            self.output_queue.put("Download not active, removing from queue if present.\n")
            # If not active, try to remove from queue directly
            self.app_instance.remove_from_queue(self.item_id)


class YTDLPGUIApp:
    def __init__(self, master):
        self.master = master
        self._setup_window(master)
        self._create_widgets()
        self._initialize_download_management()
        self._configure_yt_dlp_path()

        # Start the queue processing loop
        self.master.after(100, self._process_queue_loop)
        self.on_source_change(YOUTUBE_SOURCE)  # Initialize UI for YouTube

    def _setup_window(self, master):
        master.title("YouTube Downloader powered by yt-dlp")
        master.geometry("600x650")  # Make window larger to accommodate download items
        master.resizable(True, True)  # Allow resizing
        try:
            master.iconbitmap("ico.ico")
        except Exception:
            pass

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
        # These are initially hidden and shown by on_source_change

        row_idx += 1
        tk.Label(input_frame, text="Target URL:", font=MAIN_FONT).grid(row=row_idx, column=0, sticky="w", padx=5,
                                                                       pady=2)
        self.url_entry = tk.Entry(input_frame, font=MAIN_FONT)
        self.url_entry.grid(row=row_idx, column=1, sticky="ew", padx=5, pady=2)
        self.url_entry.bind("<Return>", self._add_to_queue_on_enter)

        row_idx += 1
        self.quality_label = tk.Label(input_frame, text="Quality:", font=MAIN_FONT)
        self.quality_var = tk.StringVar(value="High Quality - 1080p")
        self.quality_menu = tk.OptionMenu(input_frame, self.quality_var, "Low Quality - 480p", "Medium Quality - 720p",
                                          "High Quality - 1080p")
        self.quality_label.grid(row=row_idx, column=0, sticky="w", padx=5, pady=2)
        self.quality_menu.grid(row=row_idx, column=1, sticky="ew", padx=5, pady=2)

        row_idx += 1
        tk.Label(input_frame, text="Output Filename (optional):", font=MAIN_FONT).grid(row=row_idx, column=0,
                                                                                       sticky="w", padx=5, pady=2)
        self.filename_entry = tk.Entry(input_frame, font=MAIN_FONT)
        self.filename_entry.grid(row=row_idx, column=1, sticky="ew", padx=5, pady=2)

        row_idx += 1
        self.mp3_var = tk.BooleanVar()
        self.mp3_check = tk.Checkbutton(input_frame, text="Convert to MP3", variable=self.mp3_var, font=MAIN_FONT)
        self.mp3_check.grid(row=row_idx, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        row_idx += 1
        self.add_to_queue_button = tk.Button(input_frame, text="Add to Queue", command=self._add_current_to_queue,
                                             bg=COLOR_ADD_BUTTON, fg="white", font=BOLD_FONT)
        self.add_to_queue_button.grid(row=row_idx, column=0, columnspan=2, sticky="ew", pady=10)

        # --- Queue Management Section ---
        queue_control_frame = tk.Frame(self.main_frame)
        queue_control_frame.pack(fill="x", pady=5)

        self.start_queue_button = tk.Button(queue_control_frame, text="Start Queue",
                                            command=self._start_queue_processing, bg=COLOR_START_QUEUE_BUTTON,
                                            fg="white", font=BOLD_FONT)
        self.start_queue_button.pack(side="left", expand=True, fill="x", padx=2)

        self.clear_queue_button = tk.Button(queue_control_frame, text="Clear Queue", command=self._clear_queue,
                                            bg=COLOR_CLEAR_BUTTON, fg="black", font=BOLD_FONT)
        self.clear_queue_button.pack(side="left", expand=True, fill="x", padx=2)

        # --- Download Items Display Area ---
        download_items_label_frame = tk.LabelFrame(self.main_frame, text="Active & Queued Downloads", font=MAIN_FONT,
                                                   padx=5, pady=5)
        download_items_label_frame.pack(fill="both", expand=True, pady=5)
        download_items_label_frame.grid_rowconfigure(0, weight=1)
        download_items_label_frame.grid_columnconfigure(0, weight=1)

        self.download_canvas = tk.Canvas(download_items_label_frame, bg="white", highlightthickness=0)
        self.download_canvas.grid(row=0, column=0, sticky="nsew")

        self.download_scroll_y = tk.Scrollbar(download_items_label_frame, orient="vertical",
                                              command=self.download_canvas.yview)
        self.download_scroll_y.grid(row=0, column=1, sticky="ns")
        self.download_canvas.config(yscrollcommand=self.download_scroll_y.set)

        self.download_items_frame = tk.Frame(self.download_canvas, bg="white")
        self.download_canvas.create_window((0, 0), window=self.download_items_frame, anchor="nw",
                                           width=self.download_canvas.winfo_width())

        self.download_items_frame.bind("<Configure>", lambda e: self.download_canvas.configure(
            scrollregion=self.download_canvas.bbox("all")))
        self.download_canvas.bind("<Configure>", lambda e: self.download_canvas.itemconfig(
            self.download_canvas.find_withtag("download_items_frame_id"), width=e.width))

        # Tag the window created by create_window so we can update its width
        self.download_canvas.create_window((0, 0), window=self.download_items_frame, anchor="nw",
                                           tags="download_items_frame_id")
        self.download_canvas.bind('<Configure>', self._on_canvas_resize)

        # --- Status Bar ---
        self.status_bar = tk.Label(self.master, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W, font=SMALL_FONT,
                                   fg=COLOR_STATUS_READY)
        self.status_bar.pack(side="bottom", fill="x")

    def _on_canvas_resize(self, event):
        """Adjusts the width of the inner frame when the canvas resizes."""
        self.download_canvas.itemconfig("download_items_frame_id", width=event.width)

    def _initialize_download_management(self):
        self.queued_downloads = []  # List of DownloadItem objects awaiting execution
        self.active_downloads = []  # List of DownloadItem objects currently running
        self.download_item_counter = 0  # To give unique IDs to download items
        self.completed_downloads_count = 0
        self.total_downloads_added = 0
        self.all_downloads_completed = threading.Event()  # Event to signal when all are done
        self.all_downloads_completed.set()  # Initially set, as nothing is pending

    def _configure_yt_dlp_path(self):
        if hasattr(sys, '_MEIPASS'):
            self.yt_dlp_path = os.path.join(sys._MEIPASS, 'yt-dlp.exe')
        else:
            self.yt_dlp_path = 'yt-dlp.exe'

    def on_source_change(self, value):
        """Adjusts UI based on selected source (YouTube or XtremeStream)."""
        if value == YOUTUBE_SOURCE:
            self.referer_label.grid_forget()
            self.referer_entry.grid_forget()
            self.quality_label.grid()
            self.quality_menu.grid()
        else:  # XtremeStream
            self.quality_label.grid_forget()
            self.quality_menu.grid_forget()
            # Find the correct row for referer entry (assuming it follows URL entry)
            current_url_row = self.url_entry.grid_info()["row"]
            self.referer_label.grid(row=current_url_row + 1, column=0, sticky="w", padx=5, pady=2)
            self.referer_entry.grid(row=current_url_row + 1, column=1, sticky="ew", padx=5, pady=2)

    def _set_status(self, text, color="black"):
        """Updates the main status bar."""
        self.status_bar.config(text=text, fg=color)

    def _add_current_to_queue(self):
        """Adds the current input values as a new download item to the queue."""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Input Error", "Target URL is required.")
            return

        # Basic URL validation (more robust regex could be used)
        if not (url.startswith("http://") or url.startswith("https://")):
            messagebox.showwarning("Input Error", "Invalid URL. Must start with http:// or https://")
            return

        source = self.source_var.get()
        quality = self.quality_var.get()
        filename = self.filename_entry.get().strip()
        mp3_conversion = self.mp3_var.get()
        referer = self.referer_entry.get().strip() if source == XTREAM_SOURCE else ""

        self.download_item_counter += 1
        item_id = self.download_item_counter  # Unique ID for this download

        # Create a new DownloadItem instance
        new_item = DownloadItem(
            self.download_items_frame, self, item_id, url, quality, filename, mp3_conversion, source, referer
        )
        self.queued_downloads.append(new_item)
        self.total_downloads_added += 1
        self.all_downloads_completed.clear()  # Clear the event, as new downloads are pending

        self._set_status(f"Added '{url[:40]}...' to queue. Queue size: {len(self.queued_downloads)}",
                         COLOR_STATUS_READY)
        self._update_queue_control_buttons()

        # Clear input fields after adding
        self.url_entry.delete(0, END)
        self.filename_entry.delete(0, END)
        if self.source_var.get() == XTREAM_SOURCE:
            self.referer_entry.delete(0, END)

        # Force canvas scroll to update to show new item
        self.download_items_frame.update_idletasks()
        self.download_canvas.yview_moveto(1.0)  # Scroll to bottom

    def _add_to_queue_on_enter(self, event=None):
        """Handler for 'Return' key press in URL entry."""
        self._add_current_to_queue()

    def _start_queue_processing(self):
        """Starts the background thread that processes the download queue."""
        if not self.queued_downloads and not self.active_downloads:
            messagebox.showinfo("Queue Empty", "No downloads in the queue to start.")
            return

        self._set_status("Processing queue...", COLOR_STATUS_PROGRESS)
        self._process_queue()  # Call it once to kick off

    def _process_queue_loop(self):
        """Main loop for polling individual download item queues and managing concurrency."""
        # Poll queues of active downloads
        for item in list(self.active_downloads):  # Iterate over a copy to allow modification
            try:
                while True:
                    line = item.output_queue.get_nowait()
                    # You could direct this output to a dedicated log/debug window if needed,
                    # but for now, the progress bar and status label are the primary outputs per item.
                    # This is mainly to drain the queue.
                    # print(f"[{item.item_id}] {line.strip()}")
                    pass
            except queue.Empty:
                pass

        # Check for slots and start new downloads
        self._process_queue()

        # Check if all downloads are finished
        if not self.queued_downloads and not self.active_downloads and not self.all_downloads_completed.is_set():
            self.all_downloads_completed.set()  # Signal completion
            self._show_overall_completion_alert()
            self._set_status("All downloads complete!", COLOR_STATUS_COMPLETE)
            self.total_downloads_added = 0  # Reset total count
            self.completed_downloads_count = 0

        self.master.after(100, self._process_queue_loop)  # Schedule next poll

    def _process_queue(self):
        """Checks for available slots and starts downloads from the queue."""
        while len(self.active_downloads) < MAX_CONCURRENT_DOWNLOADS and self.queued_downloads:
            next_item = self.queued_downloads.pop(0)  # Get the first item from the queue
            self.active_downloads.append(next_item)
            next_item.start_download()  # Start its process in a new thread
            self._set_status(f"Starting download for '{next_item.url[:40]}...'. Active: {len(self.active_downloads)}",
                             COLOR_STATUS_PROGRESS)
            self._update_queue_control_buttons()

    def download_finished(self, item_id, success):
        """Callback from DownloadItem when it finishes."""
        item_to_remove = None
        for item in self.active_downloads:
            if item.item_id == item_id:
                item_to_remove = item
                break

        if item_to_remove:
            self.active_downloads.remove(item_to_remove)
            self.completed_downloads_count += 1
            # Schedule the UI removal after a short delay so user can see final status
            self.master.after(2000, lambda: self._remove_download_item_ui(item_to_remove))

        self._update_queue_control_buttons()
        # The _process_queue_loop will handle kicking off new downloads and overall completion alert

    def _remove_download_item_ui(self, item):
        """Removes a download item's UI frame."""
        item.frame.destroy()
        # This is important to allow the scrollbar to update correctly
        self.download_items_frame.update_idletasks()
        self.download_canvas.config(scrollregion=self.download_canvas.bbox("all"))

    def remove_from_queue(self, item_id):
        """Removes a pending download item from the queue if aborted before starting."""
        item_to_remove = None
        for item in self.queued_downloads:
            if item.item_id == item_id:
                item_to_remove = item
                break
        if item_to_remove:
            self.queued_downloads.remove(item_to_remove)
            self.completed_downloads_count += 1  # Count it as completed (aborted) for overall alert
            self._set_status(f"Removed '{item_to_remove.url[:40]}...' from queue.", COLOR_STATUS_ABORTED)
            self.master.after(500, lambda: self._remove_download_item_ui(item_to_remove))
            self._update_queue_control_buttons()

    def _clear_queue(self):
        """Clears all pending downloads from the queue and resets the UI."""
        if self.active_downloads:
            if not messagebox.askyesno("Clear Queue", "There are active downloads. Abort all active and clear queue?"):
                return
            # Abort all active first
            for item in list(self.active_downloads):  # Iterate over copy
                item.abort_download()  # This will eventually call download_finished

        # Clear queued downloads
        for item in self.queued_downloads:
            item.frame.destroy()  # Immediately remove UI for queued items
        self.queued_downloads.clear()
        self.total_downloads_added = 0
        self.completed_downloads_count = 0
        self.all_downloads_completed.set()  # Reset completion event

        self._set_status("Queue cleared. All active downloads aborted.", COLOR_STATUS_ABORTED)
        self._update_queue_control_buttons()
        self.download_items_frame.update_idletasks()
        self.download_canvas.config(scrollregion=self.download_canvas.bbox("all"))

    def _update_queue_control_buttons(self):
        """Enables/disables queue control buttons based on queue/active status."""
        start_enabled = bool(self.queued_downloads) and (len(self.active_downloads) < MAX_CONCURRENT_DOWNLOADS)
        clear_enabled = bool(self.queued_downloads) or bool(self.active_downloads)

        self.start_queue_button.config(state="normal" if start_enabled else "disabled")
        self.clear_queue_button.config(state="normal" if clear_enabled else "disabled")

    def _show_overall_completion_alert(self):
        """Shows a single alert when all downloads are finished."""
        messagebox.showinfo("All Downloads Complete", "All items in the queue have finished downloading!")
        # Optionally open the downloads folder here
        if messagebox.askyesno("Open Folder", "Open the main downloads folder?"):
            downloads_path = os.path.join(os.getcwd(), DOWNLOADS_DIR)
            if os.path.exists(downloads_path):
                os.startfile(downloads_path)
            else:
                messagebox.showerror("Error", f"Downloads folder not found: {downloads_path}")


if __name__ == "__main__":
    root = tk.Tk()
    app = YTDLPGUIApp(root)
    root.mainloop()

