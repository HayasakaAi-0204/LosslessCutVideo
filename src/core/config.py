"""Configuration module for CutVideo application.

Manages paths to portable tools (ffmpeg, ffprobe) and application settings.
"""

from pathlib import Path
import shutil
import sys


def get_project_root() -> Path:
    """Return the absolute path to the project root directory."""
    if getattr(sys, "frozen", False):
        # Running as compiled PyInstaller executable (.exe)
        return Path(sys.executable).resolve().parent
    # src/core/config.py -> src/core -> src -> project root
    return Path(__file__).resolve().parent.parent.parent


def get_tools_dir() -> Path:
    """Return the path to the tools directory containing portable binaries."""
    # 1. Check bundled PyInstaller temp directory (_MEIPASS) if packaged with --add-data
    if hasattr(sys, "_MEIPASS"):
        meipass_tools = Path(sys._MEIPASS) / "tools"
        if meipass_tools.is_dir():
            return meipass_tools

    # 2. Check portable tools/ folder next to .exe or in project root
    tools_dir = get_project_root() / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    return tools_dir


def get_ffmpeg_path() -> Path:
    """Return path to ffmpeg executable.
    
    Prefers tools/ffmpeg.exe within the project according to GEMINI.md.
    Falls back to system ffmpeg if not found in tools/.
    """
    tools_ffmpeg = get_tools_dir() / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if tools_ffmpeg.is_file():
        return tools_ffmpeg
    
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return Path(system_ffmpeg)
    
    return tools_ffmpeg


def get_ffprobe_path() -> Path:
    """Return path to ffprobe executable.
    
    Prefers tools/ffprobe.exe within the project according to GEMINI.md.
    Falls back to system ffprobe if not found in tools/.
    """
    tools_ffprobe = get_tools_dir() / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    if tools_ffprobe.is_file():
        return tools_ffprobe
    
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return Path(system_ffprobe)
    
    return tools_ffprobe


def validate_tools() -> dict[str, bool]:
    """Check if ffmpeg and ffprobe are available.
    
    Returns:
        dict with boolean status for 'ffmpeg' and 'ffprobe'.
    """
    ffmpeg_p = get_ffmpeg_path()
    ffprobe_p = get_ffprobe_path()
    return {
        "ffmpeg": ffmpeg_p.is_file(),
        "ffprobe": ffprobe_p.is_file(),
    }

