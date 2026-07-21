#!/usr/bin/env python3
"""
Simple test to identify where the crash occurs.
"""

import sys
import time
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_import():
    """Test importing the native module."""
    logger.info("Step 1: Importing native module...")
    try:
        import proctap._native_macos as native
        logger.info("✅ Import successful")
        return True
    except Exception as e:
        logger.error(f"❌ Import failed: {e}")
        return False

def test_create_tap():
    """Test creating a tap."""
    logger.info("Step 2: Creating process tap...")
    try:
        import proctap._native_macos as native
        import subprocess

        # Start a say process
        say_process = subprocess.Popen(
            ["say", "test"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        pid = say_process.pid
        logger.info(f"Say process PID: {pid}")
        time.sleep(0.2)

        logger.info("Calling create_tap...")
        handle = native.create_tap(
            include_pids=[pid],
            exclude_pids=[],
            sample_rate=16000,
            channels=1,
            bits_per_sample=16
        )
        logger.info(f"✅ create_tap successful, handle: {handle}")

        # Cleanup
        logger.info("Cleaning up...")
        try:
            native.destroy_tap(handle)
            logger.info("✅ destroy_tap successful")
        except Exception as e:
            logger.error(f"destroy_tap failed: {e}")

        say_process.kill()
        say_process.wait()

        return True
    except Exception as e:
        logger.error(f"❌ create_tap failed: {e}", exc_info=True)
        return False

def test_start_tap():
    """Test starting the tap."""
    logger.info("Step 3: Starting tap...")
    try:
        import proctap._native_macos as native
        import subprocess

        # Start a say process
        say_process = subprocess.Popen(
            ["say", "test audio"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        pid = say_process.pid
        logger.info(f"Say process PID: {pid}")
        time.sleep(0.2)

        logger.info("Creating tap...")
        handle = native.create_tap(
            include_pids=[pid],
            exclude_pids=[],
            sample_rate=16000,
            channels=1,
            bits_per_sample=16
        )
        logger.info(f"Tap created, handle: {handle}")

        logger.info("Calling start_tap...")
        native.start_tap(handle)
        logger.info("✅ start_tap successful")

        # Let it run briefly
        time.sleep(0.5)

        # Cleanup
        logger.info("Stopping tap...")
        try:
            native.stop_tap(handle)
            logger.info("✅ stop_tap successful")
        except Exception as e:
            logger.error(f"stop_tap failed: {e}")

        logger.info("Destroying tap...")
        try:
            native.destroy_tap(handle)
            logger.info("✅ destroy_tap successful")
        except Exception as e:
            logger.error(f"destroy_tap failed: {e}")

        say_process.kill()
        say_process.wait()

        return True
    except Exception as e:
        logger.error(f"❌ start_tap failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("macOS Native C Extension - Simple Test")
    logger.info("=" * 60)

    # Run tests step by step
    if not test_import():
        sys.exit(1)

    logger.info("")
    if not test_create_tap():
        sys.exit(1)

    logger.info("")
    if not test_start_tap():
        sys.exit(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("✅ All tests passed!")
    logger.info("=" * 60)

    sys.exit(0)
