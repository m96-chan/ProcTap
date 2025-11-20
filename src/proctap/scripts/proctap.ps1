#!/usr/bin/env pwsh
# PowerShell wrapper for proctap to handle binary streaming correctly
# This script works around PowerShell's text encoding issues when piping binary data

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

# Start proctap.exe as a child process
$process = New-Object System.Diagnostics.Process
$process.StartInfo = New-Object System.Diagnostics.ProcessStartInfo

$process.StartInfo.FileName = "proctap.exe"
$process.StartInfo.Arguments = ($Args -join " ")

# Redirect standard output to capture binary data
$process.StartInfo.RedirectStandardOutput = $true
$process.StartInfo.RedirectStandardError = $false
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.CreateNoWindow = $true

$process.Start() | Out-Null

# Open PowerShell's stdout as binary stream
$stdout = [Console]::OpenStandardOutput()
$buffer = New-Object byte[] 8192

# Stream binary data from proctap.exe to stdout
while (($read = $process.StandardOutput.BaseStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
    $stdout.Write($buffer, 0, $read)
    $stdout.Flush()
}

$process.WaitForExit() | Out-Null
exit $process.ExitCode
