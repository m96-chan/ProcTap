#!/usr/bin/env python3
"""
Test script for macOS native C extension backend.
Tests the fixed IOProcID handling.
"""

import sys
import time
import logging
from proctap.backends.macos_native import MacOSNativeBackend, is_available

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_native_backend():
    """Test the native backend with a simple audio capture."""

    # Check if native backend is available
    if not is_available():
        logger.error("Native backend is not available")
        return False

    logger.info("Native backend is available!")

    # Use a PID that's likely to be playing audio
    # We'll use the 'say' command to generate test audio
    import subprocess
    import os

    logger.info("Starting 'say' command to generate test audio...")
    say_process = subprocess.Popen(
        ["say", "-v", "Samantha", "Testing audio capture with native backend"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    pid = say_process.pid
    logger.info(f"Say process PID: {pid}")

    # Give it a moment to start
    time.sleep(0.3)

    try:
        # Create backend with 16kHz mono for testing
        logger.info("Creating MacOSNativeBackend...")
        backend = MacOSNativeBackend(
            pid=pid,
            sample_rate=16000,
            channels=1,
            sample_width=2
        )

        # Start capture
        logger.info("Starting audio capture...")
        backend.start()

        # Read some data
        logger.info("Reading audio data...")
        total_bytes = 0
        for i in range(10):
            data = backend.read(4096)
            total_bytes += len(data)
            logger.info(f"Read iteration {i+1}: {len(data)} bytes (total: {total_bytes} bytes)")
            time.sleep(0.1)

        # Get format info
        format_info = backend.get_format()
        logger.info(f"Audio format: {format_info}")

        # Stop capture
        logger.info("Stopping audio capture...")
        backend.stop()

        logger.info(f"✅ Test PASSED! Captured {total_bytes} bytes total")

        # Wait for say to finish
        say_process.wait(timeout=5)

        return True

    except Exception as e:
        logger.error(f"❌ Test FAILED with error: {e}", exc_info=True)

        # Kill say process if still running
        try:
            say_process.kill()
            say_process.wait(timeout=1)
        except:
            pass

        return False

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Testing macOS Native C Extension Backend")
    logger.info("=" * 60)

    success = test_native_backend()

    sys.exit(0 if success else 1)
