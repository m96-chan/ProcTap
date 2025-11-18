#!/usr/bin/env python3
"""
Cross-platform build script for ProcessAudioTap.

This script handles building, testing, and packaging for all supported platforms.
"""

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional


class Colors:
    """Terminal color codes."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'


def log(message: str, color: str = Colors.BLUE) -> None:
    """Print colored log message."""
    print(f"{color}[BUILD]{Colors.END} {message}")


def log_success(message: str) -> None:
    """Print success message."""
    log(message, Colors.GREEN)


def log_warning(message: str) -> None:
    """Print warning message."""
    log(f"WARNING: {message}", Colors.YELLOW)


def log_error(message: str) -> None:
    """Print error message."""
    log(f"ERROR: {message}", Colors.RED)


def run_command(cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run command with logging."""
    cmd_str = ' '.join(cmd)
    log(f"Running: {cmd_str}")
    
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=check
        )
        if result.stdout.strip():
            print(result.stdout)
        return result
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {cmd_str}")
        if e.stdout:
            print("STDOUT:", e.stdout)
        if e.stderr:
            print("STDERR:", e.stderr)
        if check:
            sys.exit(1)
        return e


class BuildManager:
    """Manages the build process for ProcessAudioTap."""
    
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.system = platform.system()
        self.architecture = platform.machine()
        self.python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        
        log(f"Build system: {self.system} {self.architecture}")
        log(f"Python version: {self.python_version}")
        
    def check_prerequisites(self) -> bool:
        """Check if all prerequisites are available."""
        log("Checking prerequisites...")
        
        # Check Python version
        if sys.version_info < (3, 10):
            log_error(f"Python 3.10+ required, got {self.python_version}")
            return False
        
        # Platform-specific checks
        if self.system == "Windows":
            return self._check_windows_prereqs()
        elif self.system == "Linux":
            return self._check_linux_prereqs()
        elif self.system == "Darwin":
            return self._check_macos_prereqs()
        else:
            log_warning(f"Unsupported platform: {self.system}")
            return True  # Continue anyway
    
    def _check_windows_prereqs(self) -> bool:
        """Check Windows prerequisites."""
        # Check for Visual Studio Build Tools or Visual Studio
        try:
            result = run_command(["cl.exe"], check=False)
            if result.returncode != 0:
                log_error("Visual Studio Build Tools not found. Please install Visual Studio Build Tools with MSVC.")
                log_error("Download from: https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022")
                return False
        except FileNotFoundError:
            log_error("Visual Studio Build Tools not found. cl.exe not in PATH.")
            return False
        
        log_success("Visual Studio Build Tools found")
        return True
    
    def _check_linux_prereqs(self) -> bool:
        """Check Linux prerequisites."""
        # Check for PulseAudio tools
        missing_tools = []
        for tool in ["pactl", "parec"]:
            result = run_command(["which", tool], check=False)
            if result.returncode != 0:
                missing_tools.append(tool)
        
        if missing_tools:
            log_warning(f"Missing PulseAudio tools: {', '.join(missing_tools)}")
            log("Install with: sudo apt-get install pulseaudio-utils")
        
        # Check for development libraries (optional)
        try:
            run_command(["pkg-config", "--exists", "libpulse"], check=False)
        except FileNotFoundError:
            log_warning("pkg-config not found. Some optional features may not work.")
        
        return True
    
    def _check_macos_prereqs(self) -> bool:
        """Check macOS prerequisites."""
        # Check macOS version
        import subprocess
        version_output = subprocess.check_output(["sw_vers", "-productVersion"], text=True).strip()
        major, minor = map(int, version_output.split('.')[:2])
        
        if major < 14 or (major == 14 and minor < 4):
            log_warning(f"macOS 14.4+ recommended for full functionality, detected {version_output}")
        
        # Check for Swift
        try:
            result = run_command(["swift", "--version"], check=False)
            if result.returncode == 0:
                log_success("Swift toolchain found")
            else:
                log_warning("Swift toolchain not found. macOS backend will be limited.")
        except FileNotFoundError:
            log_warning("Swift not found. Install Xcode or Swift toolchain.")
        
        return True
    
    def clean(self) -> None:
        """Clean build artifacts."""
        log("Cleaning build artifacts...")
        
        patterns = [
            "build/",
            "dist/",
            "*.egg-info/",
            "**/__pycache__/",
            "**/*.pyc",
            "**/*.pyo",
            "**/*.so",
            "**/*.dll",
            "**/*.dylib",
            ".mypy_cache/",
            ".pytest_cache/",
            ".coverage",
            "htmlcov/",
        ]
        
        import glob
        import shutil
        
        for pattern in patterns:
            for path in glob.glob(pattern, recursive=True):
                path_obj = Path(path)
                if path_obj.exists():
                    if path_obj.is_dir():
                        shutil.rmtree(path_obj)
                        log(f"Removed directory: {path}")
                    else:
                        path_obj.unlink()
                        log(f"Removed file: {path}")
    
    def install_dependencies(self, dev: bool = False) -> None:
        """Install project dependencies."""
        log("Installing dependencies...")
        
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "pip"]
        run_command(cmd)
        
        # Install build dependencies
        cmd = [sys.executable, "-m", "pip", "install", "build", "wheel"]
        run_command(cmd)
        
        # Install project in editable mode
        if dev:
            cmd = [sys.executable, "-m", "pip", "install", "-e", ".[dev,contrib]"]
        else:
            cmd = [sys.executable, "-m", "pip", "install", "-e", "."]
        
        run_command(cmd)
    
    def build_swift_helper(self) -> bool:
        """Build Swift helper for macOS."""
        if self.system != "Darwin":
            return True
        
        swift_dir = self.root_dir / "swift" / "proctap-macos"
        if not swift_dir.exists():
            log_warning("Swift helper source not found")
            return False
        
        log("Building Swift helper...")
        try:
            run_command(["swift", "build", "-c", "release"], cwd=swift_dir)
            
            # Copy binary to package
            bin_dir = self.root_dir / "src" / "proctap" / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            
            binary_src = swift_dir / ".build" / "release" / "proctap-macos"
            binary_dst = bin_dir / "proctap-macos"
            
            if binary_src.exists():
                import shutil
                shutil.copy2(binary_src, binary_dst)
                os.chmod(binary_dst, 0o755)
                log_success(f"Built Swift helper: {binary_dst}")
                return True
            else:
                log_error("Swift binary not found after build")
                return False
                
        except Exception as e:
            log_error(f"Swift build failed: {e}")
            return False
    
    def build_package(self) -> None:
        """Build the Python package."""
        log("Building package...")
        
        # Build Swift helper first if on macOS
        if self.system == "Darwin":
            self.build_swift_helper()
        
        # Build wheel
        cmd = [sys.executable, "-m", "build", "--wheel"]
        run_command(cmd)
        
        # Build source distribution
        cmd = [sys.executable, "-m", "build", "--sdist"]
        run_command(cmd)
        
        log_success("Package built successfully")
    
    def run_tests(self, coverage: bool = False) -> None:
        """Run tests."""
        log("Running tests...")
        
        if coverage:
            cmd = [sys.executable, "-m", "pytest", "--cov=proctap", "--cov-report=html", "--cov-report=term"]
        else:
            cmd = [sys.executable, "-m", "pytest", "-v"]
        
        run_command(cmd)
        
        if coverage:
            log_success("Test coverage report generated in htmlcov/")
    
    def run_type_check(self) -> None:
        """Run type checking."""
        log("Running type checks...")
        cmd = [sys.executable, "-m", "mypy", "src/proctap"]
        run_command(cmd)
    
    def run_linting(self) -> None:
        """Run code linting."""
        log("Running linting...")
        
        # Try to install and run common linters
        linters = [
            (["flake8", "src/proctap"], "flake8"),
            (["black", "--check", "src/proctap"], "black"),
            (["isort", "--check-only", "src/proctap"], "isort"),
        ]
        
        for cmd, name in linters:
            try:
                run_command(cmd, check=False)
            except FileNotFoundError:
                log_warning(f"{name} not installed, skipping")
    
    def install_package(self) -> None:
        """Install the built package."""
        log("Installing package...")
        
        dist_dir = self.root_dir / "dist"
        wheels = list(dist_dir.glob("*.whl"))
        
        if not wheels:
            log_error("No wheel found. Run build first.")
            sys.exit(1)
        
        # Install the latest wheel
        latest_wheel = max(wheels, key=lambda p: p.stat().st_mtime)
        cmd = [sys.executable, "-m", "pip", "install", "--force-reinstall", str(latest_wheel)]
        run_command(cmd)
        
        log_success(f"Installed: {latest_wheel.name}")
    
    def create_dev_environment(self) -> None:
        """Create development environment setup."""
        log("Setting up development environment...")
        
        # Create .vscode settings if not exists
        vscode_dir = self.root_dir / ".vscode"
        vscode_dir.mkdir(exist_ok=True)
        
        settings_file = vscode_dir / "settings.json"
        if not settings_file.exists():
            settings = {
                "python.defaultInterpreterPath": "./venv/bin/python",
                "python.linting.enabled": True,
                "python.linting.mypyEnabled": True,
                "python.formatting.provider": "black",
                "python.sortImports.args": ["--profile", "black"],
                "files.exclude": {
                    "**/__pycache__": True,
                    "**/*.pyc": True,
                    ".mypy_cache": True,
                    ".pytest_cache": True,
                    "build": True,
                    "dist": True,
                    "*.egg-info": True
                }
            }
            
            import json
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            
            log_success("Created .vscode/settings.json")
        
        # Install dev dependencies
        self.install_dependencies(dev=True)


def main():
    parser = argparse.ArgumentParser(description="Build script for ProcessAudioTap")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts")
    parser.add_argument("--build", action="store_true", help="Build package")
    parser.add_argument("--test", action="store_true", help="Run tests")
    parser.add_argument("--coverage", action="store_true", help="Run tests with coverage")
    parser.add_argument("--typecheck", action="store_true", help="Run type checking")
    parser.add_argument("--lint", action="store_true", help="Run linting")
    parser.add_argument("--install", action="store_true", help="Install built package")
    parser.add_argument("--dev", action="store_true", help="Set up development environment")
    parser.add_argument("--all", action="store_true", help="Run clean, build, test sequence")
    parser.add_argument("--check-prereqs", action="store_true", help="Check prerequisites only")
    
    args = parser.parse_args()
    
    # Default to build if no arguments
    if not any(vars(args).values()):
        args.build = True
    
    root_dir = Path(__file__).parent.resolve()
    build_manager = BuildManager(root_dir)
    
    try:
        # Check prerequisites
        if not build_manager.check_prerequisites():
            if args.check_prereqs:
                sys.exit(1)
            log_warning("Some prerequisites missing, continuing anyway...")
        
        if args.check_prereqs:
            log_success("All prerequisites satisfied")
            return
        
        if args.clean or args.all:
            build_manager.clean()
        
        if args.dev:
            build_manager.create_dev_environment()
            return
        
        if args.build or args.all:
            build_manager.install_dependencies()
            build_manager.build_package()
        
        if args.test or args.all:
            build_manager.run_tests()
        
        if args.coverage:
            build_manager.run_tests(coverage=True)
        
        if args.typecheck:
            build_manager.run_type_check()
        
        if args.lint:
            build_manager.run_linting()
        
        if args.install:
            build_manager.install_package()
        
        if args.all:
            log_success("Build sequence completed successfully!")
        
    except KeyboardInterrupt:
        log_error("Build interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Build failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()