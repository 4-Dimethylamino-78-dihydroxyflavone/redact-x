#!/usr/bin/env python3
"""
Build script for creating standalone executable of PDF Redactor.

This script uses PyInstaller to create a single executable file
that includes all dependencies.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


def check_requirements():
    """Check if required packages are installed."""
    required = ['PyInstaller', 'pymupdf', 'Pillow']
    optional = ['pytesseract', 'opencv-python', 'numpy']

    print("Checking requirements...")

    missing = []
    for package in required:
        try:
            __import__(package.lower().replace('-', '_'))
            print(f"✓ {package} found")
        except ImportError:
            missing.append(package)
            print(f"✗ {package} missing")

    if missing:
        print(f"\nError: Missing required packages: {', '.join(missing)}")
        print("Install with: pip install " + " ".join(missing))
        return False

    # Check optional packages
    print("\nChecking optional packages (for OCR support)...")
    ocr_available = True
    for package in optional:
        try:
            __import__(package.lower().replace('-', '_'))
            print(f"✓ {package} found")
        except ImportError:
            ocr_available = False
            print(f"✗ {package} missing (OCR will be disabled)")

    return True


def build_executable():
    """Build the standalone executable."""
    script_dir = Path(__file__).parent
    main_script = script_dir / "redact_unified.py"

    if not main_script.exists():
        print(f"Error: {main_script} not found!")
        return False

    # PyInstaller options
    options = [
        '--name=PDFRedactor',
        '--onefile',  # Single executable file
        '--windowed',  # No console window (for GUI)
        '--add-data', f'{script_dir}/README.md:.',  # Include README
        '--icon=NONE',  # Add your icon file here if you have one
        '--clean',  # Clean PyInstaller cache
        '--noconfirm',  # Overwrite output directory
    ]

    # Add hidden imports for packages that PyInstaller might miss
    hidden_imports = [
        'tkinter',
        'tkinter.ttk',
        'tkinter.scrolledtext',
        'PIL._tkinter_finder',
    ]

    for imp in hidden_imports:
        options.extend(['--hidden-import', imp])

    # Build command
    cmd = ['pyinstaller'] + options + [str(main_script)]

    print("\nBuilding executable...")
    print("Command:", ' '.join(cmd))

    try:
        result = subprocess.run(cmd, check=True)
        print("\n✓ Build completed successfully!")

        # Find the output executable
        dist_dir = script_dir / 'dist'
        if sys.platform == 'win32':
            exe_path = dist_dir / 'PDFRedactor.exe'
        else:
            exe_path = dist_dir / 'PDFRedactor'

        if exe_path.exists():
            print(f"\nExecutable created at: {exe_path}")
            print(f"Size: {exe_path.stat().st_size / 1024 / 1024:.1f} MB")

            # Create a distribution folder with all necessary files
            dist_folder = script_dir / 'PDFRedactor_Distribution'
            dist_folder.mkdir(exist_ok=True)

            # Copy executable
            shutil.copy2(exe_path, dist_folder)

            # Copy README
            readme_src = script_dir / 'README.md'
            if readme_src.exists():
                shutil.copy2(readme_src, dist_folder)

            # Create a simple batch/shell script to run the app
            if sys.platform == 'win32':
                launcher = dist_folder / 'Run_PDFRedactor.bat'
                launcher.write_text('@echo off\nstart PDFRedactor.exe\n')
            else:
                launcher = dist_folder / 'Run_PDFRedactor.sh'
                launcher.write_text('#!/bin/bash\n./PDFRedactor\n')
                launcher.chmod(0o755)

            print(f"\nDistribution folder created at: {dist_folder}")
            print("\nContents:")
            for file in dist_folder.iterdir():
                print(f"  - {file.name}")

            return True
        else:
            print("\nError: Executable not found in expected location!")
            return False

    except subprocess.CalledProcessError as e:
        print(f"\nError: Build failed with exit code {e.returncode}")
        return False
    except Exception as e:
        print(f"\nError: {e}")
        return False


def clean_build_artifacts():
    """Clean up build artifacts."""
    script_dir = Path(__file__).parent

    dirs_to_remove = ['build', 'dist', '__pycache__']
    files_to_remove = ['*.spec']

    print("\nCleaning build artifacts...")

    for dir_name in dirs_to_remove:
        dir_path = script_dir / dir_name
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"  Removed {dir_name}/")

    for pattern in files_to_remove:
        for file in script_dir.glob(pattern):
            file.unlink()
            print(f"  Removed {file.name}")


def main():
    """Main build process."""
    print("PDF Redactor Standalone Build Script")
    print("=" * 40)

    # Check Python version
    if sys.version_info < (3, 8):
        print("Error: Python 3.8 or higher is required!")
        return 1

    # Parse arguments
    if len(sys.argv) > 1 and sys.argv[1] == 'clean':
        clean_build_artifacts()
        return 0

    # Check requirements
    if not check_requirements():
        return 1

    # Build
    if build_executable():
        print("\n" + "=" * 40)
        print("Build completed successfully!")
        print("\nTo distribute the application, share the contents of")
        print("the 'PDFRedactor_Distribution' folder.")
        print("\nTo clean build artifacts, run: python build_standalone.py clean")
        return 0
    else:
        print("\nBuild failed!")
        return 1


if __name__ == '__main__':
    sys.exit(main())