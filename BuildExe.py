import os
import shutil
import sys
import subprocess
import urllib.request

YT_DLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
YT_DLP_EXE = "yt-dlp.exe"
FFMPEG_EXE = "ffmpeg.exe"  # Define FFmpeg executable name
APP_EXE_NAME = "UniversalVideoDownloader.exe"  # Define the main application executable name


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


def is_ffmpeg_available(location='path'):
    """
    Checks if FFmpeg is available in PATH or in the local directory.
    location='path': checks system PATH
    location='local': checks current working directory
    """
    if location == 'path':
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                           timeout=5)
            print(f"✔️ FFmpeg found in system PATH.")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            print(f"⚠️ FFmpeg not found in system PATH.")
            return False
    elif location == 'local':
        if os.path.isfile(FFMPEG_EXE):
            print(f"✔️ {FFMPEG_EXE} found in current directory.")
            return True
        else:
            print(f"⚠️ {FFMPEG_EXE} not found in current directory.")
            return False
    return False


def build_exe(ffmpeg_to_bundle=False):
    import PyInstaller.__main__

    pyinstaller_args = [
        'UniversalVideoDownloader.py',
        '--onefile',
        '--windowed',
        '--icon=Ico.ico',
        f'--add-binary={YT_DLP_EXE};.'  # Always bundle yt-dlp.exe
    ]

    if ffmpeg_to_bundle:
        # Check if ffmpeg.exe exists locally to bundle it
        if os.path.isfile(FFMPEG_EXE):
            pyinstaller_args.append(f'--add-binary={FFMPEG_EXE};.')
            print(f"📦 Bundling {FFMPEG_EXE} from current directory.")
        else:
            print(f"❌ Cannot bundle {FFMPEG_EXE}. File not found in current directory.")
            print(f"   Please download FFmpeg (e.g., from https://www.gyan.dev/ffmpeg/builds/ )")
            print(f"   and place {FFMPEG_EXE} (and its required DLLs if any) in the project root.")
            print("   Proceeding without FFmpeg bundling.")

    PyInstaller.__main__.run(pyinstaller_args)


def move_exe_to_root():
    dist_folder = 'dist'
    exe_path = os.path.join(dist_folder, APP_EXE_NAME)  # Use APP_EXE_NAME
    if os.path.isfile(exe_path):
        shutil.move(exe_path, APP_EXE_NAME)  # Use APP_EXE_NAME
        print(f"✅ Moved {APP_EXE_NAME} to root folder.")
    else:
        print(f"⚠️ EXE not found in {dist_folder}. Nothing moved.")


def delete_existing_exe():
    """Deletes the main application executable if it exists in the root directory."""
    if os.path.isfile(APP_EXE_NAME):
        try:
            os.remove(APP_EXE_NAME)
            print(f"🗑️ Deleted existing {APP_EXE_NAME}.")
        except OSError as e:
            print(f"❌ Error deleting existing {APP_EXE_NAME}: {e}")
            print("Please close any running instances of the application and try again.")
            sys.exit(1)
    else:
        print(f"✔️ No existing {APP_EXE_NAME} found to delete.")


def clean_build_files():
    folders = ['build', '__pycache__', 'dist']
    files = ['UniversalVideoDownloader.spec']  # This assumes your spec file name

    for folder in folders:
        if os.path.isdir(folder):
            shutil.rmtree(folder)
            print(f"🗑️ Deleted folder: {folder}")

    for file in files:
        if os.path.isfile(file):
            os.remove(file)
            print(f"🗑️ Deleted file: {file}")


if __name__ == "__main__":
    if not os.path.isfile('UniversalVideoDownloader.py'):
        print("❌ Error: UniversalVideoDownloader.py not found in the current directory.")
        sys.exit(1)

    ensure_installed('PyInstaller')
    download_yt_dlp()

    # Determine FFmpeg bundling status
    bundle_ffmpeg = False
    if not is_ffmpeg_available(location='path'):
        print("FFmpeg is not in system PATH.")
        if is_ffmpeg_available(location='local'):
            print(f"Found {FFMPEG_EXE} in current directory. It will be bundled.")
            bundle_ffmpeg = True
        else:
            print(f"FFmpeg will NOT be bundled as {FFMPEG_EXE} was not found in the current directory.")
            print(f"To bundle FFmpeg, please download a static build (e.g., from https://www.gyan.dev/ffmpeg/builds/ )")
            print(
                f"and place the {FFMPEG_EXE} (and any accompanying DLLs like 'ffplay.exe', 'ffprobe.exe' if part of the package) in the project root.")
            print(
                "You can still proceed with the build, but local video conversion might not work if FFmpeg is not otherwise available.")
    else:
        print("FFmpeg is in system PATH, so it will not be bundled (relying on system installation).")

    # Delete existing EXE before building
    delete_existing_exe()

    print("🚀 Building EXE...\n")
    sys.stdout.flush()
    build_exe(ffmpeg_to_bundle=bundle_ffmpeg)

    move_exe_to_root()

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
        print("⚠️ Could not prompt for cleanup (stdin not available).")