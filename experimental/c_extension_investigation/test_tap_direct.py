#!/usr/bin/env python3
"""
Test if we can read from the Process Tap directly without aggregate device.
"""

import ctypes
import ctypes.util
import subprocess
import time

# Load Core Audio
ca_lib = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))
foundation_lib = ctypes.CDLL(ctypes.util.find_library("Foundation"))

# Load objc runtime
objc = ctypes.CDLL(ctypes.util.find_library("objc"))

# Setup objc functions
objc.objc_getClass.restype = ctypes.c_void_p
objc.sel_registerName.restype = ctypes.c_void_p
objc.objc_msgSend.restype = ctypes.c_void_p
objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

# Create CATapDescription
CATapDescription = objc.objc_getClass(b"CATapDescription")
if not CATapDescription:
    print("❌ CATapDescription class not found")
    exit(1)

alloc_sel = objc.sel_registerName(b"alloc")
init_sel = objc.sel_registerName(b"init")

tap_desc = objc.objc_msgSend(CATapDescription, alloc_sel)
tap_desc = objc.objc_msgSend(tap_desc, init_sel)

print(f"✅ CATapDescription created: {tap_desc}")

# Start say process
say_proc = subprocess.Popen(['say', 'Testing direct tap access'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
pid = say_proc.pid
print(f"Say process PID: {pid}")
time.sleep(0.3)

# Add process to tap
setProcesses_sel = objc.sel_registerName(b"setProcesses:")
objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

# Create NSArray with the PID
# This is simplified - in reality we'd need proper CF/NS array creation
# For now, let's just create the tap with the description

# Get UUID from tap description
UUID_sel = objc.sel_registerName(b"UUID")
objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
objc.objc_msgSend.restype = ctypes.c_void_p
tap_uuid_obj = objc.objc_msgSend(tap_desc, UUID_sel)

# Get UUID string
UUIDString_sel = objc.sel_registerName(b"UUIDString")
uuid_str_obj = objc.objc_msgSend(tap_uuid_obj, UUIDString_sel)

# Get C string from NSString
UTF8String_sel = objc.sel_registerName(b"UTF8String")
objc.objc_msgSend.restype = ctypes.c_char_p
uuid_cstr = objc.objc_msgSend(uuid_str_obj, UTF8String_sel)
print(f"Tap UUID: {uuid_cstr.decode()}")

# Create process tap
tap_id = ctypes.c_uint32(0)
status = ca_lib.AudioHardwareCreateProcessTap(tap_desc, ctypes.byref(tap_id))
print(f"AudioHardwareCreateProcessTap: status={status}, tapID={tap_id.value}")

if status == 0 and tap_id.value != 0:
    print(f"✅ Process tap created with ID: {tap_id.value}")

    # Now let's try to create an IOProc DIRECTLY on the tap device (not aggregate)
    print("\n" + "="*60)
    print("ATTEMPTING TO USE TAP DIRECTLY AS INPUT DEVICE")
    print("="*60)

    # Define IOProc callback type
    IOProc = ctypes.CFUNCTYPE(
        ctypes.c_int32,  # OSStatus
        ctypes.c_uint32,  # AudioObjectID
        ctypes.c_void_p,  # const AudioTimeStamp* inNow
        ctypes.c_void_p,  # const AudioBufferList* inInputData
        ctypes.c_void_p,  # const AudioTimeStamp* inInputTime
        ctypes.c_void_p,  # AudioBufferList* outOutputData
        ctypes.c_void_p,  # const AudioTimeStamp* inOutputTime
        ctypes.c_void_p   # void* inClientData
    )

    buffer_count = {"count": 0, "bytes": 0}

    def io_callback(device, in_now, in_input, in_input_time, out_output, in_output_time, client_data):
        buffer_count["count"] += 1
        if buffer_count["count"] % 100 == 0:
            print(f"[IOPROC] Called {buffer_count['count']} times")
        return 0  # noErr

    io_proc = IOProc(io_callback)

    # Try to create IOProc on tap device
    proc_id = ctypes.c_void_p(0)
    status = ca_lib.AudioDeviceCreateIOProcID(
        tap_id.value,
        io_proc,
        None,
        ctypes.byref(proc_id)
    )

    print(f"AudioDeviceCreateIOProcID on tap: status={status}")

    if status != 0:
        print(f"❌ Cannot create IOProc on tap device directly (status={status})")
        print(f"   This is expected - taps likely need to be used via aggregate devices")
    else:
        print(f"✅ IOProc created on tap device!")

        # Try to start it
        status = ca_lib.AudioDeviceStart(tap_id.value, proc_id)
        print(f"AudioDeviceStart on tap: status={status}")

        if status == 0:
            print("✅ Tap device started! Listening for 2 seconds...")
            time.sleep(2)
            print(f"IOProc was called {buffer_count['count']} times")

            ca_lib.AudioDeviceStop(tap_id.value, proc_id)
            ca_lib.AudioDeviceDestroyIOProcID(tap_id.value, proc_id)

    # Cleanup
    ca_lib.AudioHardwareDestroyProcessTap(tap_id)
else:
    print("❌ Failed to create process tap")

say_proc.kill()
say_proc.wait()
