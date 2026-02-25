import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

def clean_directories(directories):
    """
    Robustly removes specified directories.
    Handles common Windows permission issues by retrying.
    """
    for directory in directories:
        if directory.exists():
            print(f"🧹 Cleaning: {directory}...")
            # Attempt to remove with retries for Windows stability
            max_retries = 3
            for i in range(max_retries):
                try:
                    shutil.rmtree(directory)
                    break
                except Exception as e:
                    if i < max_retries - 1:
                        print(f"  ⏳ Retry {i+1} cleaning {directory.name}...")
                        time.sleep(1)
                    else:
                        print(f"  ⚠️  Warning: Could not fully clean {directory.name}: {e}")

def create_dist_package():
    """
    Creates a clean staging area, bundles the application, and optionally runs PyInstaller.
    """
    # Configuration
    PROJECT_ROOT = Path('.').resolve()
    STAGING_DIR = PROJECT_ROOT / 'dist_staging'
    DIST_DIR = PROJECT_ROOT / 'dist'
    BUILD_DIR = PROJECT_ROOT / 'build'
    SPEC_FILE = PROJECT_ROOT / 'biliutility.spec'

    print(f"🚀 Starting Build Process for BiliUtility...")
    print(f"📂 Project Root: {PROJECT_ROOT}")
    
    # 1. Handle Cleaning
    cleanup_dirs = [STAGING_DIR, BUILD_DIR, DIST_DIR]

    # Check if we should only clean
    should_clean_only = '--clean' in sys.argv
    should_build = '--build' in sys.argv

    if should_clean_only:
        clean_directories(cleanup_dirs)
        print("✨ Project cleaned.")
        if not should_build:
            return

    # Always wipe dist_staging before copying — prevents FileExistsError on repeat runs.
    # build/ and dist/ are only wiped when --clean is explicitly passed (they hold
    # PyInstaller artifacts that are expensive to regenerate).
    clean_directories([STAGING_DIR])
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    print("🏗️  Preparing staging area...")

    # 2. Copy Core Directories
    # 'app' is the new Python package core
    core_folders = ['app', 'static', 'templates', 'blcsdk', 'audio_commands', 'tts_engines']
    for folder in core_folders:
        src = PROJECT_ROOT / folder
        dest = STAGING_DIR / folder
        if src.exists():
            # Filter out pycache and other garbage
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', '*.log'))
            print(f"  ✅ Copied folder: {folder}")
        else:
            print(f"  ⚠️  Missing optional folder: {folder}")

    # 3. Copy Root Files
    core_files = [
        'plugin.json', 
        'README.md',
        'requirements.txt',
        'biliutility.spec'
    ]
    for file in core_files:
        src = PROJECT_ROOT / file
        if src.exists():
            shutil.copy2(src, STAGING_DIR / file)
            print(f"  ✅ Copied file: {file}")

    # 4. Create Directory Structure
    # Data directory
    (STAGING_DIR / 'data').mkdir(exist_ok=True)
    env_example = PROJECT_ROOT / 'data' / '.env.example'
    if env_example.exists():
        shutil.copy2(env_example, STAGING_DIR / 'data' / '.env.example')
    
    # Log directory
    (STAGING_DIR / 'log').mkdir(exist_ok=True)
    with open(STAGING_DIR / 'log' / '.gitkeep', 'w') as f:
        pass
    
    print("\n📦 Staging complete at 'dist_staging/'")

    # 5. Run PyInstaller
    if not should_build:
        print("\nℹ️  Run with --build to execute PyInstaller automatically.")
        return

    print("\n🔨 Running PyInstaller...")
    start_time = time.time()
    
    try:
        # We need to ensure PyInstaller is available
        # Using sys.executable to run the module ensures we use the current venv
        cmd = [
            sys.executable, '-m', 'PyInstaller',
            '--clean',
            '--distpath', str(DIST_DIR),
            '--workpath', str(BUILD_DIR),
            '--noconfirm',
            str(SPEC_FILE)
        ]
        
        subprocess.run(cmd, check=True)
        
        duration = time.time() - start_time
        print(f"\n✨ Build Success! ({duration:.2f}s)")
        print(f"👉 Executable located in: {DIST_DIR / 'biliutility'}")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Build Failed with error code {e.returncode}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    create_dist_package()
