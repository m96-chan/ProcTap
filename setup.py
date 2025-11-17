from setuptools import setup, Extension
from setuptools import find_packages
from setuptools.command.build_py import build_py
import sys
import platform
import os
import subprocess
from pathlib import Path

# Platform-specific extension modules
ext_modules = []


class BuildPyCommand(build_py):
    """Custom build command to build Swift helper on macOS."""

    def run(self):
        # Build Swift helper on macOS
        if platform.system() == "Darwin":
            self.build_swift_helper()

        # Run standard build
        build_py.run(self)

    def build_swift_helper(self):
        """Build the Swift CLI helper for macOS."""
        swift_dir = Path("swift/proctap-macos")
        if not swift_dir.exists():
            print("WARNING: Swift helper source directory not found, skipping Swift build")
            return

        print("Building Swift CLI helper for macOS...")
        try:
            # Build with SwiftPM in release mode
            subprocess.run(
                ["swift", "build", "-c", "release"],
                cwd=swift_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            print("Swift build completed successfully")

            # Copy binary to package bin directory
            bin_dir = Path("src/proctap/bin")
            bin_dir.mkdir(parents=True, exist_ok=True)

            binary_src = swift_dir / ".build" / "release" / "proctap-macos"
            binary_dst = bin_dir / "proctap-macos"

            if binary_src.exists():
                import shutil
                shutil.copy2(binary_src, binary_dst)
                print(f"Copied Swift helper to {binary_dst}")

                # Make executable
                os.chmod(binary_dst, 0o755)
            else:
                print(f"WARNING: Built binary not found at {binary_src}")

        except subprocess.CalledProcessError as e:
            print(f"WARNING: Swift build failed: {e}")
            print(f"stdout: {e.stdout}")
            print(f"stderr: {e.stderr}")
            print("macOS backend will not be functional")
        except FileNotFoundError:
            print("WARNING: Swift compiler not found. Install Xcode or Swift toolchain.")
            print("macOS backend will not be functional")


# Build native extension only on Windows
if platform.system() == "Windows":
    ext_modules = [
        Extension(
            "proctap._native",
            sources=["src/proctap/_native.cpp"],
            language="c++",
            extra_compile_args=["/std:c++20", "/EHsc", '/utf-8'] if sys.platform == 'win32' else [],
            libraries=[
                'ole32', 'uuid', 'propsys'
                # CoInitializeEx, CoCreateInstance, CoTaskMemAlloc/Free など
                # "Avrt",   # 将来、AVRT 系の API (AvSetMmThreadCharacteristicsW 等) を使うなら追加
                # "Mmdevapi", # 今は LoadLibrary で動的ロードなので必須ではない
            ],
        )
    ]
    print("Building with Windows WASAPI backend (C++ extension)")

elif platform.system() == "Linux":
    # Linux: Pure Python backend using PulseAudio (experimental)
    print("Building for Linux with PulseAudio backend (experimental)")
    print("NOTE: Per-process isolation has limitations on Linux")

elif platform.system() == "Darwin":  # macOS
    # macOS: Native C extension + Swift CLI helper fallback
    ext_modules = [
        Extension(
            "proctap._native_macos",
            sources=["src/proctap/_native_macos.m"],
            language="c",
            extra_compile_args=[
                # Note: NOT using -fobjc-arc due to compatibility issues with CoreAudio constants
                # Manual memory management is required
                "-ObjC",
                "-O2",  # Moderate optimization (O3 can cause issues)
            ],
            extra_link_args=[
                "-framework", "CoreAudio",
                "-framework", "AudioToolbox",
                "-framework", "Foundation",
            ],
        )
    ]
    print("Building for macOS with Core Audio Process Tap backend (macOS 14.4+)")
    print("NOTE: Building native C extension for optimal performance")
    print("NOTE: Swift CLI helper will be built as fallback if Swift toolchain is available")

else:
    print(f"WARNING: Platform '{platform.system()}' is not officially supported")
    print("The package will install but audio capture will not work")

setup(
    name="proc-tap",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    ext_modules=ext_modules,
    package_data={
        "proctap": ["bin/proctap-macos"],  # Include Swift helper binary
    },
    cmdclass={
        "build_py": BuildPyCommand,
    },
)