---
name: ⚡ Performance Issue
about: Report performance problems or suggest optimizations
title: "[Performance]: "
labels: performance
assignees: ''
---

## Performance Issue Description

<!-- Describe the performance problem you're experiencing -->
<!-- The audio capture is experiencing high latency / CPU usage / memory usage... -->

## Performance Issue Type

<!-- What type of performance issue are you experiencing? -->
<!-- Options: High CPU Usage, High Memory Usage, Audio Latency/Delay, Dropped Frames/Buffer Underruns, Slow Startup Time, Other -->

- **Type**:

## Performance Measurements

<!-- Provide quantitative measurements if possible -->

- CPU Usage: % (expected: %)
- Memory Usage: MB (expected: MB)
- Latency: ms (expected: ms)
- Audio dropout rate: per minute

## Reproduction Steps

<!-- How can we reproduce this performance issue? -->

1. Start capturing from process with PID ...
2. Monitor CPU/memory usage
3. Observe high resource consumption after X minutes

## Code Example

<!-- Provide code that demonstrates the performance issue -->

```python
from proctap import ProcessAudioTap

# Code that exhibits poor performance
```

## System Information

<!-- Provide detailed system information -->

- **ProcTap Version**: <!-- e.g., 0.1.0 -->
- **Python Version**: <!-- e.g., 3.11.5 -->
- **OS**: <!-- e.g., Windows 11 22H2, Ubuntu 22.04, macOS 14.4 -->
- **CPU**: <!-- e.g., Intel i7-12700K, AMD Ryzen 9 5950X -->
- **RAM**: <!-- e.g., 32 GB -->
- **Target Process**: <!-- e.g., VRChat.exe, Chrome.exe -->

## Configuration Details

<!-- What configuration are you using? -->

- Sample Rate: kHz
- Channels: (mono/stereo)
- Buffer Size: ms
- Callback frequency: Every ms

## Profiling Data (Optional)

<!-- If you've done any profiling, share the results -->

```
Paste profiling output, flamegraphs, or performance traces here...
```

## Optimization Ideas

<!-- Do you have any ideas on how to improve performance? -->

Possible optimizations:
- Reduce memory allocations
- Use larger buffers
- Optimize threading model

## Comparison with Alternatives

<!-- Have you compared with other solutions? (check all that apply) -->

- [ ] The performance issue does NOT occur with system-wide capture
- [ ] The performance issue does NOT occur with other audio capture tools
- [ ] The issue appears to be specific to certain target processes

## Additional Context

<!-- Any other context about the performance issue -->
<!-- Any additional information, graphs, or screenshots... -->
