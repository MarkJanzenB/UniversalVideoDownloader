# Universal Video Downloader & Converter

A powerful and user-friendly desktop application built using Python and Tkinter. It allows you to download videos from a variety of online sources and convert local media files to MP4 or MP3 formats. It uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) for content downloading and [FFmpeg](https://ffmpeg.org/) for media conversion tasks.

---

## 🌟 Key Features

- **Download from Multiple Sources**: Supports a wide range of websites via `yt-dlp`.
- **Convert Local Videos**: Transform your local video files to MP4 or extract audio as MP3.
- **Audio Extraction**: Convert any supported media to MP3 with ease.
- **Quality Selection**: Choose preferred download resolution such as Auto, 1080p, 720p, or 480p.
- **Custom File Naming**: Define a filename for downloaded or converted files.
- **Parallel Downloads**: Handle multiple downloads concurrently with limit control.
- **Queue System**: Queue tasks, abort active ones, retry failed ones, or remove any.
- **Download History**: Keep track of completed, failed, or cancelled tasks.
- **Live Logs**: View live yt-dlp and FFmpeg output for transparency and debugging.
- **Settings Persistence**: Preferences like output folder and quality are saved.
- **Windows Executable**: Build a portable `.exe` using PyInstaller, bundling yt-dlp and optionally FFmpeg.

---

## 🚀 Getting Started

### Requirements

- Python 3.8 or higher
- `pip` package manager

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/your-username/UniversalVideoDownloader.git
   cd UniversalVideoDownloader
   ```

2. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

   If the requirements file is missing, install manually:

   ```bash
   pip install PyInstaller
   ```

### yt-dlp Setup

Running `BuildExe.py` will automatically download `yt-dlp.exe`.  
If you're not building an EXE, manually place `yt-dlp.exe` in the same folder as `UniversalVideoDownloader.py` or in your system `PATH`.

Download yt-dlp manually:  
➡️ https://github.com/yt-dlp/yt-dlp/releases

### FFmpeg Setup (Optional but Recommended)

To enable conversion features:

- **Portable Option**:  
  Download static FFmpeg build from https://www.gyan.dev/ffmpeg/builds/ and place `ffmpeg.exe` in the root directory.

- **System Install**:  
  Install FFmpeg globally and add it to your `PATH`.

---

## 🛠 Running the App

### Run from Python source

```bash
python UniversalVideoDownloader.py
```

### Build Windows Executable

```bash
python BuildExe.py
```

This will:

- Install PyInstaller if needed
- Download `yt-dlp.exe` if not already present
- Bundle `ffmpeg.exe` if found
- Remove old EXE if it exists
- Build a new `UniversalVideoDownloader.exe`
- Clean up build artifacts optionally

---

## 💡 How to Use

### Input Options

- **Source Types**:
  - `Default`: For general video sites
  - `XtremeStream`: Use a referer URL for sites that need it
  - `Local`: Select and convert a local video file

- **Input Fields**:
  - Provide the video URL or choose a local file
  - For `XtremeStream`, also supply a referer
  - Select desired output quality
  - Optionally set a custom output filename
  - Enable MP3 conversion for audio-only extraction

### Queue Controls

- **Add to Queue**: Enqueue the job
- **Abort**: Stop active tasks
- **Open File**: View finished files in explorer
- **Retry**: Re-attempt failed or cancelled downloads
- **Remove**: Remove jobs from the queue or history

### Settings Menu

Accessible from `Options > Settings`:

- Set max concurrent downloads
- Choose default quality per source
- Set output directory
- Toggle confirmation on delete
- Enable log view on launch

### View Logs

Enable from `View > Show Process Log` to view yt-dlp and FFmpeg terminal output.

---

## ⚠️ Disclaimer

This application is provided **"AS IS"**, without warranties or guarantees.  
The authors and contributors are not liable for any misuse or legal consequences.

Always comply with the terms of service and copyright laws for the websites and content you use with this tool.

This software uses the following third-party tools:

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [FFmpeg](https://ffmpeg.org/)

Users are responsible for compliance with their licenses and terms of use.

---

## 🤝 Contributions

Have a bug or suggestion? Contributions are welcome!

- Open an issue
- Fork the project and submit a pull request

---

## 📄 License

This project is open source.  
Built with Python, Tkinter, yt-dlp, and FFmpeg.
