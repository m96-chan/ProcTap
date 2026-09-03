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

def _processtap_app_package_data():
    """Enumerate a pre-staged, signed+notarized proctap-helper.app for packaging.

    The Process Tap helper is NOT built here (it needs Developer ID signing +
    notarization, done in CI by swift/proctap-helper/ci_sign_notarize.sh, which
    stages the bundle into src/proctap/bin/proctap-helper.app). setup.py only
    packages it when present.
    """
    app = Path("src/proctap/bin/proctap-helper.app")
    if not app.is_dir():
        return []
    return [
        str(p.relative_to("src/proctap"))
        for p in app.rglob("*")
        if p.is_file()
    ]


# On macOS the wheel bundles platform-specific Swift helper binaries
# (screencapture-audio, the signed proctap-helper.app). Without a platform tag
# the macOS wheel would be 'py3-none-any' — colliding with the Linux/Windows
# pure-Python wheel on publish, so only one survives and the macOS binaries are
# dropped. Tag macOS wheels 'py3-none-macosx_*' instead: platform-specific (no
# collision, installs only on macOS) yet Python-version-agnostic (one wheel for
# all 3.x).
_cmdclass = {"build_py": BuildPyCommand}
try:
    try:
        from setuptools.command.bdist_wheel import bdist_wheel as _bdist_wheel  # setuptools>=70.1
    except ImportError:
        from wheel.bdist_wheel import bdist_wheel as _bdist_wheel  # type: ignore[no-redef]

    class _PlatformWheel(_bdist_wheel):  # type: ignore[valid-type,misc]
        def finalize_options(self):
            super().finalize_options()
            if platform.system() == "Darwin":
                # Mark non-pure so the tag carries a macosx_* platform.
                self.root_is_pure = False

        def get_tag(self):
            impl, abi, plat = super().get_tag()
            if platform.system() == "Darwin":
                return ("py3", "none", plat)
            return (impl, abi, plat)

    _cmdclass["bdist_wheel"] = _PlatformWheel
except ImportError:
    pass  # wheel/bdist_wheel unavailable (e.g. sdist-only build); keep default tag


setup(
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    ext_modules=ext_modules,
    package_data={
        "proctap": [
            "bin/screencapture-audio",  # ScreenCaptureKit Swift helper (bundleID-based)
            *_processtap_app_package_data(),  # signed Process Tap helper (.app), if staged
        ],
    },
    cmdclass=_cmdclass,
)