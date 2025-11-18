#!/bin/bash
set -e

# Linux/macOS build script for ProcessAudioTap

echo "🔨 ProcessAudioTap Build Script (Linux/macOS)"
echo "=============================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log() {
    echo -e "${BLUE}[BUILD]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    error "Python 3 is not installed or not in PATH"
    exit 1
fi

PYTHON=$(command -v python3)
PYTHON_VERSION=$($PYTHON --version | cut -d' ' -f2 | cut -d'.' -f1-2)

log "Using Python: $PYTHON ($PYTHON_VERSION)"

# Check Python version
if [[ $(echo "$PYTHON_VERSION >= 3.10" | bc -l) -eq 0 ]]; then
    error "Python 3.10+ required, got $PYTHON_VERSION"
    exit 1
fi

# Platform-specific setup
case "$(uname -s)" in
    Linux*)
        log "Detected Linux platform"
        
        # Check for PulseAudio
        if ! command -v pactl &> /dev/null; then
            warning "PulseAudio tools not found. Install with:"
            echo "  sudo apt-get install pulseaudio-utils"
        fi
        
        # Check for development packages
        if ! pkg-config --exists libpulse 2>/dev/null; then
            warning "PulseAudio development libraries not found. Install with:"
            echo "  sudo apt-get install libpulse-dev"
        fi
        ;;
    Darwin*)
        log "Detected macOS platform"
        
        # Check macOS version
        MACOS_VERSION=$(sw_vers -productVersion)
        log "macOS version: $MACOS_VERSION"
        
        # Check for Swift
        if command -v swift &> /dev/null; then
            SWIFT_VERSION=$(swift --version | head -n1)
            success "Swift found: $SWIFT_VERSION"
        else
            warning "Swift not found. Install Xcode or Swift toolchain for full functionality"
        fi
        
        # Check for Xcode Command Line Tools
        if ! xcode-select -p &> /dev/null; then
            warning "Xcode Command Line Tools not found. Install with:"
            echo "  xcode-select --install"
        fi
        ;;
    *)
        warning "Unsupported platform: $(uname -s)"
        ;;
esac

# Parse arguments
CLEAN=false
BUILD=true
TEST=false
INSTALL=false
DEV=false
COVERAGE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --clean)
            CLEAN=true
            shift
            ;;
        --test)
            TEST=true
            shift
            ;;
        --install)
            INSTALL=true
            shift
            ;;
        --dev)
            DEV=true
            BUILD=false
            shift
            ;;
        --coverage)
            TEST=true
            COVERAGE=true
            shift
            ;;
        --all)
            CLEAN=true
            BUILD=true
            TEST=true
            shift
            ;;
        --help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --clean      Clean build artifacts"
            echo "  --test       Run tests"
            echo "  --install    Install built package"
            echo "  --dev        Set up development environment"
            echo "  --coverage   Run tests with coverage"
            echo "  --all        Clean, build, and test"
            echo "  --help       Show this help"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Clean if requested
if [[ "$CLEAN" == true ]]; then
    log "Cleaning build artifacts..."
    rm -rf build/ dist/ *.egg-info/
    find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    find . -name "*.pyc" -delete 2>/dev/null || true
    find . -name "*.pyo" -delete 2>/dev/null || true
    rm -rf .mypy_cache/ .pytest_cache/ .coverage htmlcov/
    success "Cleaned build artifacts"
fi

# Set up development environment
if [[ "$DEV" == true ]]; then
    log "Setting up development environment..."
    
    # Install/upgrade pip
    $PYTHON -m pip install --upgrade pip
    
    # Install build tools
    $PYTHON -m pip install build wheel
    
    # Install project in development mode
    $PYTHON -m pip install -e ".[dev,contrib]"
    
    # Create virtual environment if it doesn't exist
    if [[ ! -d "venv" ]]; then
        log "Creating virtual environment..."
        $PYTHON -m venv venv
        success "Created virtual environment in ./venv"
        echo "Activate with: source venv/bin/activate"
    fi
    
    success "Development environment ready"
    exit 0
fi

# Build package
if [[ "$BUILD" == true ]]; then
    log "Installing dependencies..."
    $PYTHON -m pip install --upgrade pip build wheel
    
    # Install project dependencies
    $PYTHON -m pip install -e .
    
    log "Building package..."
    
    # Build Swift helper on macOS
    if [[ "$(uname -s)" == "Darwin" ]] && command -v swift &> /dev/null; then
        SWIFT_DIR="swift/proctap-macos"
        if [[ -d "$SWIFT_DIR" ]]; then
            log "Building Swift helper..."
            cd "$SWIFT_DIR"
            swift build -c release
            cd - > /dev/null
            
            # Copy binary
            BIN_DIR="src/proctap/bin"
            mkdir -p "$BIN_DIR"
            cp "$SWIFT_DIR/.build/release/proctap-macos" "$BIN_DIR/"
            chmod +x "$BIN_DIR/proctap-macos"
            success "Built Swift helper"
        fi
    fi
    
    # Build Python package
    $PYTHON -m build
    
    success "Package built successfully"
fi

# Run tests
if [[ "$TEST" == true ]]; then
    log "Running tests..."
    
    if [[ "$COVERAGE" == true ]]; then
        $PYTHON -m pytest --cov=proctap --cov-report=html --cov-report=term
        success "Tests completed with coverage report in htmlcov/"
    else
        $PYTHON -m pytest -v
        success "Tests completed"
    fi
fi

# Install package
if [[ "$INSTALL" == true ]]; then
    log "Installing package..."
    
    # Find the latest wheel
    WHEEL=$(find dist/ -name "*.whl" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
    
    if [[ -z "$WHEEL" ]]; then
        error "No wheel found. Run build first."
        exit 1
    fi
    
    $PYTHON -m pip install --force-reinstall "$WHEEL"
    success "Installed: $(basename "$WHEEL")"
fi

success "Build script completed successfully!"