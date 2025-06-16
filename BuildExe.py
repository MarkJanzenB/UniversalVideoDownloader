import os
import shutil
import sys
import subprocess
import urllib.request

YT_DLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
YT_DLP_EXE = "yt-dlp.exe"

def ensure_installed(package):
    try:
        __import__(package)
    except ModuleNotFoundError:
        print(f"📦 {package} not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def download_yt_dlp():
    if not os.path.isfile(YT_DLP_EXE):
        print(f"🌐 Downloading {YT_DLP_EXE} from {YT_DLP_URL}...")
        try:
            urllib.request.urlretrieve(YT_DLP_URL, YT_DLP_EXE)
            print(f"✅ Downloaded {YT_DLP_EXE}")
        except Exception as e:
            print(f"❌ Failed to download yt-dlp.exe: {e}")
            sys.exit(1)
    else:
        print(f"✔️ {YT_DLP_EXE} already exists.")

def build_exe():
    import PyInstaller.__main__
    PyInstaller.__main__.run([
        'YoutubeDownloader.py',
        '--onefile',
        '--windowed',
        '--icon=Ico.ico',
        f'--add-binary={YT_DLP_EXE};.'
    ])

def move_exe_to_root():
    dist_folder = 'dist'
    exe_name = 'YoutubeDownloader.exe'
    exe_path = os.path.join(dist_folder, exe_name)
    if os.path.isfile(exe_path):
        shutil.move(exe_path, exe_name)
        print(f"✅ Moved {exe_name} to root folder.")
    else:
        print(f"⚠️ EXE not found in {dist_folder}. Nothing moved.")

def clean_build_files():
    folders = ['build', '__pycache__', 'dist']
    files = ['YoutubeDownloader.spec']

    for folder in folders:
        if os.path.isdir(folder):
            shutil.rmtree(folder)
            print(f"🗑️ Deleted folder: {folder}")

    for file in files:
        if os.path.isfile(file):
            os.remove(file)
            print(f"🗑️ Deleted file: {file}")

if __name__ == "__main__":
    if not os.path.isfile('YoutubeDownloader.py'):
        print("❌ Error: YoutubeDownloader.py not found in the current directory.")
        sys.exit(1)

    ensure_installed('PyInstaller')
    download_yt_dlp()

    print("🚀 Building EXE...\n")
    sys.stdout.flush()
    build_exe()

    move_exe_to_root()

    # Ensure the prompt shows up before exiting
    print("\n✅ Build complete!")
    sys.stdout.flush()

    try:
        response = input("❓ Do you want to delete build files (build/, dist/, spec, etc)? (y/n): ").strip().lower()
        if response == 'y':
            clean_build_files()
            print("✅ Cleanup done.")
        else:
            print("⚠️ Skipped cleanup.")
    except EOFError:
        # This can happen if PyInstaller hijacks stdin
        print("⚠️ Could not prompt for cleanup (stdin not available).")
