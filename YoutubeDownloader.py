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

        self.elapsed_label = tk.Label(self.main_frame, text="Elapsed: 00:00:00 | 0.0%", font=("Inter", 9))
        self.elapsed_label.grid(row=7, column=0, sticky="w", padx=5)

        self.output_box = scrolledtext.ScrolledText(self.main_frame, wrap=tk.WORD, font=("Roboto", 9), height=5)
        self.output_box.grid(row=8, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        self.output_box.config(state="disabled")

        self.main_frame.grid_rowconfigure(8, weight=1)

        self.status_bar = tk.Label(master, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W, font=("Inter", 9), fg="black")
        self.status_bar.pack(side="bottom", fill="x")

        self.output_queue = queue.Queue()
        self.current_process = None
        self.start_time = None

        if hasattr(sys, '_MEIPASS'):
            self.yt_dlp_path = os.path.join(sys._MEIPASS, 'yt-dlp.exe')
        else:
            self.yt_dlp_path = 'yt-dlp.exe'

        self.master.after(100, self.poll_queues)
        self.on_source_change("YouTube")

    def on_source_change(self, value):
        if value == "YouTube":
            self.referer_label.grid_forget()
            self.referer_entry.grid_forget()
            self.quality_label.grid()
            self.quality_menu.grid()
        else:
            self.quality_label.grid_forget()
            self.quality_menu.grid_forget()
            self.referer_label.grid(row=2, column=0, sticky="w", padx=5)
            self.referer_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=5)

    def set_status(self, text, color="black"):
        self.status_bar.config(text=text, fg=color)

    def start_download_thread(self):
        url = self.url_entry.get().strip()
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
        self.start_time = time.time()

        command = self.build_command(url)
        threading.Thread(target=self.run_yt_dlp, args=(command,), daemon=True).start()

    def build_command(self, url):
        command = [self.yt_dlp_path, url]
        if self.source_var.get() == "XtremeStream" and self.referer_entry.get().strip():
            command += ["--add-header", f"referer: {self.referer_entry.get().strip()}"]

        downloads_dir = os.path.join(os.getcwd(), 'downloads')
        temp_dir = os.path.join(downloads_dir, 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        command += ["--paths", f"temp:{temp_dir}"]

        out_name = self.filename_entry.get().strip() or "%(title)s"
        if self.mp3_var.get():
            out_name += ".mp3"
            command += ["--extract-audio", "--audio-format", "mp3"]
        else:
            out_name += ".mp4"
            command += ["--recode-video", "mp4"]

        command += ["--output", os.path.join(downloads_dir, out_name)]

        if self.source_var.get() == "YouTube":
            q = self.quality_var.get()
            if "1080" in q:
                command += ['-f', 'bestvideo[height>=1080]+bestaudio/best[height<=1080]']
            elif "720" in q:
                command += ['-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]']
            elif "480" in q:
                command += ['-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]']

        return command

    def run_yt_dlp(self, command):
        self.output_queue.put(f"Executing: {' '.join(command)}\n")
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            self.current_process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True, creationflags=creationflags
            )
            for line in self.current_process.stdout:
                self.output_queue.put(line)
                percent = self.extract_percentage(line)
                if percent is not None:
                    self.progress_bar.config(value=percent)
                    self.set_status("Downloading...", "blue")
                if "ffmpeg" in line.lower() or "merging formats" in line.lower():
                    self.set_status("Converting...", "blue")

            rc = self.current_process.wait()
            if rc == 0:
                self.set_status("Download Complete!", "green")
                self.show_completion_alert()
            else:
                self.set_status(f"Failed (Exit {rc})", "red")
        except Exception as e:
            self.set_status(f"Error: {e}", "red")
            self.output_queue.put(f"Error: {e}\n")
        finally:
            self.reset_ui()
            shutil.rmtree(os.path.join(os.getcwd(), 'downloads', 'temp'), ignore_errors=True)

    def abort_download(self):
        if self.current_process:
            try:
                self.current_process.kill()
            except Exception:
                pass
        self.output_queue.put("\nProcess aborted by user.\n")
        self.set_status("Download Aborted", "orange")
        self.reset_ui()

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
            percent = self.progress_bar['value']
            self.elapsed_label.config(text=f"Elapsed: {h:02}:{m:02}:{s:02} | {percent:.1f}%")

        self.master.after(100, self.poll_queues)

    def update_output(self, text):
        self.output_box.config(state="normal")
        self.output_box.insert(END, text)
        self.output_box.see(END)
        self.output_box.config(state="disabled")

    def extract_percentage(self, line):
        try:
            parts = line.split()
            for part in parts:
                if part.endswith('%'):
                    value = float(part.strip('%'))
                    return value
        except Exception:
            pass
        return None

    def reset_ui(self):
        self.download_button.config(state="normal")
        self.abort_button.config(state="disabled")
        self.restart_button.config(state="normal")
        self.progress_bar.stop()
        self.progress_bar.config(value=0, mode="determinate")
        self.set_input_fields_state("normal")
        self.start_time = None
        if "Download" not in self.status_bar.cget("text"):
            self.set_status("Ready", "black")

    def set_input_fields_state(self, state):
        for widget in [self.url_entry, self.filename_entry, self.source_menu, self.mp3_check, self.quality_menu, self.referer_entry]:
            widget.config(state=state)

    def restart_download(self):
        self.start_download_thread()

    def show_completion_alert(self):
        if messagebox.askokcancel("Download Complete", "The download has finished. Open download folder?"):
            os.startfile(os.path.join(os.getcwd(), 'downloads'))

    def start_download_on_enter(self, event=None):
        self.start_download_thread()

if __name__ == "__main__":
    root = tk.Tk()
    app = YTDLPGUIApp(root)
    root.mainloop()
