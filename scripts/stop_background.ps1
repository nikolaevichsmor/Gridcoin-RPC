$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$ScriptPaths = @(
    (Join-Path $ProjectRoot "main.py"),
    (Join-Path $PSScriptRoot "main.pyw")
)
$BinaryPaths = @(
    (Join-Path $ProjectRoot "Gridcoin-RPC.exe"),
    (Join-Path $ProjectRoot "dist\Gridcoin-RPC.exe"),
    (Join-Path $ProjectRoot "dist\Gridcoin-RPC\Gridcoin-RPC.exe")
)

Get-CimInstance Win32_Process | Where-Object {
    $Process = $_
    if ($Process.Name -ieq "Gridcoin-RPC.exe") {
        $BinaryPaths -contains $Process.ExecutablePath
    } elseif ($Process.Name -in @("python.exe", "pythonw.exe", "python3.exe", "py.exe", "pyw.exe")) {
        # Require the script to be the first argument and belong to this checkout.
        # Relative paths cannot be attributed safely to a working directory.
        foreach ($ScriptPath in $ScriptPaths) {
            $EscapedPath = [regex]::Escape($ScriptPath)
            $ScriptArgument = '"' + $EscapedPath + '"'
            if ($ScriptPath -notmatch '\s') {
                $ScriptArgument += '|' + $EscapedPath
            }
            if ($Process.CommandLine -match ('^\s*(?:"[^"]+"|\S+)\s+(?:' + $ScriptArgument + ')(?:\s|$)')) {
                $true
                break
            }
        }
    }
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped PID" $_.ProcessId
}
