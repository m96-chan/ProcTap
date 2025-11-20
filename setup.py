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
        """Build the Swift CLI helper for ScreenCaptureKit backend on macOS."""
        swift_dir = Path("src/proctap/swift/screencapture-audio")
        if not swift_dir.exists():
            print("WARNING: Swift helper source directory not found, skipping Swift build")
            print(f"  Expected: {swift_dir}")
            return

        print("Building ScreenCaptureKit Swift helper for macOS...")
        try:
            # Build with SwiftPM in release mode
            result = subprocess.run(
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

            # Detect architecture (arm64 or x86_64)
            import platform as plat
            arch = plat.machine()
            if arch == "arm64":
                build_arch = "arm64-apple-macosx"
            else:
                build_arch = "x86_64-apple-macosx"

            binary_src = swift_dir / ".build" / build_arch / "release" / "screencapture-audio"
            binary_dst = bin_dir / "screencapture-audio"

            if binary_src.exists():
                import shutil
                shutil.copy2(binary_src, binary_dst)
                print(f"Copied Swift helper to {binary_dst}")

                # Make executable
                os.chmod(binary_dst, 0o755)
            else:
                print(f"WARNING: Built binary not found at {binary_src}")
                print(f"  Checked architecture: {build_arch}")

        except subprocess.CalledProcessError as e:
            print(f"WARNING: Swift build failed: {e}")
            print(f"stdout: {e.stdout}")
            print(f"stderr: {e.stderr}")
            print("ScreenCaptureKit backend will not be functional")
        except FileNotFoundError:
            print("WARNING: Swift compiler not found. Install Xcode or Swift toolchain.")
            print("ScreenCaptureKit backend will not be functional")


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
    # macOS: ScreenCaptureKit backend via Swift CLI helper (no C extension needed)
    print("Building for macOS with ScreenCaptureKit backend (macOS 13+)")
    print("NOTE: Swift helper binary will be built and bundled automatically")

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
        "proctap": ["bin/screencapture-audio"],  # Include ScreenCaptureKit Swift helper
    },
    cmdclass={
        "build_py": BuildPyCommand,
    },
)