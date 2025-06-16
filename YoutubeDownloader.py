import tkinter as tk
from tkinter import scrolledtext, messagebox, END, ttk
import subprocess
import sys
import os
import threading
import queue
import shutil
import time

class YTDLPGUIApp:
    def __init__(self, master):
        self.master = master
        master.title("YouTube Downloader powered by yt-dlp")
        master.geometry("400x520")
        master.resizable(False, False)

        try:
            master.iconbitmap("ico.ico")
        except Exception:
            pass

        self.main_frame = tk.Frame(master)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.main_frame.grid_columnconfigure(1, weight=1)

        tk.Label(self.main_frame, text="Source:", font=("Inter", 10)).grid(row=0, column=0, sticky="w", padx=5)
        self.source_var = tk.StringVar(value="YouTube")
        self.source_menu = tk.OptionMenu(self.main_frame, self.source_var, "YouTube", "XtremeStream", command=self.on_source_change)
        self.source_menu.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        self.referer_label = tk.Label(self.main_frame, text="Referer URL:", font=("Inter", 10))
        self.referer_entry = tk.Entry(self.main_frame, font=("Inter", 10))

        tk.Label(self.main_frame, text="Target URL:", font=("Inter", 10)).grid(row=1, column=0, sticky="w", padx=5)
        self.url_entry = tk.Entry(self.main_frame, font=("Inter", 10))
        self.url_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        self.url_entry.bind("<Return>", self.start_download_on_enter)

        self.quality_label = tk.Label(self.main_frame, text="Quality:", font=("Inter", 10))
        self.quality_var = tk.StringVar(value="High Quality - 1080p")
        self.quality_menu = tk.OptionMenu(self.main_frame, self.quality_var, "Low Quality - 480p", "Medium Quality - 720p", "High Quality - 1080p")
        self.quality_label.grid(row=2, column=0, sticky="w", padx=5)
        self.quality_menu.grid(row=2, column=1, sticky="ew", padx=5, pady=5)

        tk.Label(self.main_frame, text="Output Filename (optional):", font=("Inter", 10)).grid(row=3, column=0, sticky="w", padx=5)
        self.filename_entry = tk.Entry(self.main_frame, font=("Inter", 10))
        self.filename_entry.grid(row=3, column=1, sticky="ew", padx=5, pady=5)

        self.mp3_var = tk.BooleanVar()
        self.mp3_check = tk.Checkbutton(self.main_frame, text="Convert to MP3", variable=self.mp3_var, font=("Inter", 10))
        self.mp3_check.grid(row=4, column=0, columnspan=2, sticky="w", padx=5, pady=5)

        self.button_frame = tk.Frame(self.main_frame)
        self.button_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=10)

        self.download_button = tk.Button(self.button_frame, text="Download", command=self.start_download_thread, bg="#4CAF50", fg="white", font=("Inter", 12, "bold"))
        self.download_button.pack(side="left", expand=True, fill="x", padx=2)

        self.abort_button = tk.Button(self.button_frame, text="Abort", command=self.abort_download, bg="#f44336", fg="white", font=("Inter", 12, "bold"), state="disabled")
        self.abort_button.pack(side="left", expand=True, fill="x", padx=2)

        self.restart_button = tk.Button(self.button_frame, text="Restart", command=self.restart_download, bg="#2196F3", fg="white", font=("Inter", 12, "bold"), state="disabled")
        self.restart_button.pack(side="left", expand=True, fill="x", padx=2)

        self.progress_bar = ttk.Progressbar(self.main_frame, orient="horizontal", mode="determinate")
        self.progress_bar.grid(row=6, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

        self.progress_label = tk.Label(self.main_frame, text="0%", anchor="center", font=("Inter", 9, "bold"))
        self.progress_label.place(in_=self.progress_bar, relx=0.5, rely=0.5, anchor="center")

        self.elapsed_label = tk.Label(self.main_frame, text="Elapsed: 00:00:00", font=("Inter", 9))
        self.elapsed_label.grid(row=7, column=0, sticky="w", padx=5)

        self.percent_label = tk.Label(self.main_frame, text="0%", font=("Inter", 9))
        self.percent_label.grid(row=7, column=1, sticky="e", padx=5)

        self.output_box = scrolledtext.ScrolledText(self.main_frame, wrap=tk.WORD, font=("Roboto", 9), height=5)
        self.output_box.grid(row=8, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        self.output_box.config(state="disabled")

        self.main_frame.grid_rowconfigure(8, weight=1)

        self.status_bar = tk.Label(master, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W, font=("Inter", 9))
        self.status_bar.pack(side="bottom", fill="x")

        self.output_queue = queue.Queue()
        self.last_command = None
        self.current_process = None
        self.last_progress_value = -1
        self.start_time = None

        if hasattr(sys, '_MEIPASS'):
            self.yt_dlp_path = os.path.join(sys._MEIPASS, 'yt-dlp.exe')
        else:
            self.yt_dlp_path = 'yt-dlp.exe'

        self.master.after(100, self.poll_queues)
        self.on_source_change("YouTube")

    def set_input_fields_state(self, state):
        widgets = [
            self.url_entry, self.filename_entry,
            self.source_menu, self.mp3_check,
            self.quality_menu, self.referer_entry
        ]
        for widget in widgets:
            widget.config(state=state)

    def on_source_change(self, value):
        if value == "YouTube":
            self.referer_label.grid_forget()
            self.referer_entry.grid_forget()
            self.quality_label.grid(row=2, column=0, sticky="w", padx=5)
            self.quality_menu.grid(row=2, column=1, sticky="ew", padx=5, pady=5)
        else:
            self.quality_label.grid_forget()
            self.quality_menu.grid_forget()
            self.referer_label.grid(row=2, column=0, sticky="w", padx=5)
            self.referer_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=5)

    def update_output(self, text):
        self.output_box.config(state="normal")
        self.output_box.insert(END, text)
        self.output_box.see(END)
        self.output_box.config(state="disabled")

    def set_status(self, text, color="black"):
        self.status_bar.config(text=text, fg=color)

    def start_download_on_enter(self, event=None):
        self.start_download_thread()

    def start_download_thread(self):
        url = self.url_entry.get().strip()
        referer = self.referer_entry.get().strip()
        filename = self.filename_entry.get().strip()
        source = self.source_var.get()
        mp3 = self.mp3_var.get()

        if not url:
            messagebox.showwarning("Input Error", "Target URL is required.")
            return

        self.output_box.config(state="normal")
        self.output_box.delete(1.0, END)
        self.output_box.config(state="disabled")

        self.set_status("Starting download...", "blue")
        self.download_button.config(state="disabled")
        self.abort_button.config(state="normal")
        self.restart_button.config(state="disabled")
        self.set_input_fields_state("disabled")
        self.progress_bar.config(mode="determinate", value=0)
        self.progress_label.config(text="0%")
        self.percent_label.config(text="0%")
        self.last_progress_value = -1
        self.start_time = time.time()
        self.elapsed_label.config(text="Elapsed: 00:00:00")

        command = [self.yt_dlp_path, url]

        if source == "XtremeStream" and referer:
            command += ["--add-header", f"referer: {referer}"]

        downloads_dir = os.path.join(os.getcwd(), 'downloads')
        os.makedirs(downloads_dir, exist_ok=True)

        temp_dir = os.path.join(downloads_dir, 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        command += ["--paths", f"temp:{temp_dir}"]

        out_name = os.path.splitext(filename)[0] if filename else "%(title)s"
        out_name += ".mp3" if mp3 else ".mp4"
        command += ["--output", os.path.join(downloads_dir, out_name)]

        if mp3:
            command += ["--extract-audio", "--audio-format", "mp3"]
        else:
            command += ["--recode-video", "mp4"]

        if source == "YouTube":
            q = self.quality_var.get()
            if q == "High Quality - 1080p":
                command += ['-f', 'bestvideo[height>=1080]+bestaudio/best[height<=1080]']
            elif q == "Medium Quality - 720p":
                command += ['-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]']
            elif q == "Low Quality - 480p":
                command += ['-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]']

        self.last_command = command
        threading.Thread(target=self._run_yt_dlp, args=(command, downloads_dir, temp_dir), daemon=True).start()

    def _run_yt_dlp(self, command, downloads_dir, temp_dir):
        self.output_queue.put(f"Executing: {' '.join(command)}\n")
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            self.current_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                creationflags=creationflags
            )

            for line in iter(self.current_process.stdout.readline, ''):
                self.output_queue.put(line)
                self.parse_progress_line(line)

            rc = self.current_process.wait()
            if rc == 0:
                self.set_status("Download Complete!", "green")
                self.show_completion_alert(downloads_dir)
            else:
                self.set_status(f"Failed (Exit {rc})", "red")
        except Exception as e:
            self.set_status(f"Error: {e}", "red")
            self.output_queue.put(f"Error: {e}\n")
        finally:
            self.download_button.config(state="normal")
            self.abort_button.config(state="disabled")
            self.restart_button.config(state="normal")
            self.progress_bar.stop()
            self.progress_bar.config(value=0, mode="determinate")
            self.progress_label.config(text="0%")
            self.percent_label.config(text="0%")
            self.set_input_fields_state("normal")
            shutil.rmtree(temp_dir, ignore_errors=True)
            self.start_time = None

    def parse_progress_line(self, line):
        if '[download]' in line and '%' in line:
            try:
                percent_str = line.split('[download]')[1].split('%')[0].strip()
                percent_float = float(percent_str)
                if abs(percent_float - self.last_progress_value) >= 1:
                    self.last_progress_value = percent_float
                    self.progress_bar.config(value=percent_float)
                    self.progress_label.config(text=f"{percent_float:.1f}%")
                    self.percent_label.config(text=f"{percent_float:.1f}%")
                    if not self.status_bar.cget("text").startswith("Downloading"):
                        self.set_status("Downloading...", "blue")
            except:
                pass
        elif any(x in line for x in ['[ExtractAudio]', '[ffmpeg]', '[Merger]']):
            if self.progress_bar["mode"] != "indeterminate":
                self.progress_bar.config(mode="indeterminate")
                self.progress_bar.start(10)
                self.progress_label.config(text="")
                self.set_status("Converting...", "blue")

    def poll_queues(self):
        try:
            while True:
                line = self.output_queue.get_nowait()
                self.update_output(line)
        except queue.Empty:
            pass

        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            self.elapsed_label.config(text=f"Elapsed: {h:02}:{m:02}:{s:02}")

        self.master.after(100, self.poll_queues)

    def show_completion_alert(self, downloads_dir):
        if messagebox.askokcancel("Download Complete", "The download has finished. Open download folder?"):
            os.startfile(downloads_dir)

    def abort_download(self):
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()
            self.set_status("Download Aborted", "orange")
            self.output_queue.put("\nProcess aborted by user.\n")
            self.download_button.config(state="normal")
            self.abort_button.config(state="disabled")
            self.restart_button.config(state="normal")
            self.progress_bar.stop()
            self.progress_bar.config(value=0, mode="determinate")
            self.progress_label.config(text="0%")
            self.percent_label.config(text="0%")
            self.set_input_fields_state("normal")
            self.start_time = None

    def restart_download(self):
        if self.last_command:
            self.progress_bar.config(value=0, mode="determinate")
            self.progress_label.config(text="0%")
            self.percent_label.config(text="0%")
            self.start_download_thread()

if __name__ == "__main__":
    root = tk.Tk()
    app = YTDLPGUIApp(root)
    root.mainloop()
