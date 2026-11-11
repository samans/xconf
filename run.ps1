<#
.SYNOPSIS
    Native-Windows launcher for the xconf multi-protocol lab.

.DESCRIPTION
    PowerShell equivalent of run.py for running the lab on native
    Windows 11 (no WSL2, no Docker). It starts each component as a hidden
    background process, records its PID under state\pids\, and stops them
    by PID. The `reset` verb delegates to `python run.py reset`, whose
    datastore logic is pure, cross-platform Python.

.PARAMETER Command
    start | stop | status | reset

.PARAMETER Target
    netconf | restconf | coreconf | client | all   (default: all)
    For `reset`, the target set is netconf | restconf | coreconf | all.

.EXAMPLE
    .\run.ps1 start all
    .\run.ps1 stop client
    .\run.ps1 status
    .\run.ps1 reset all

.NOTES
    If scripts are blocked, run once in the shell:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    or invoke as:
        powershell -ExecutionPolicy Bypass -File .\run.ps1 start all
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('start', 'stop', 'status', 'reset')]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Target = 'all'
)

$ErrorActionPreference = 'Stop'

# --- paths (mirror run.py) -------------------------------------------------
$Root  = Split-Path -Parent $MyInvocation.MyCommand.Path
$State = Join-Path $Root 'state'
$Pids  = Join-Path $State 'pids'
$Logs  = Join-Path $State 'logs'

$ClientUrl = 'http://127.0.0.1:8080'

# Resolve the Python interpreter: prefer the launcher 'py', else 'python'.
function Get-Python {
    foreach ($cand in @('py', 'python', 'python3')) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) {
            # 'py' needs -3 to pick Python 3.
            if ($cand -eq 'py') { return @{ Exe = $cmd.Source; Prefix = @('-3') } }
            return @{ Exe = $cmd.Source; Prefix = @() }
        }
    }
    throw "No Python interpreter found on PATH (looked for py, python, python3)."
}

$Py = Get-Python

# Component -> script path (mirror run.py COMPONENTS).
$Components = [ordered]@{
    netconf  = Join-Path $Root 'servers\netconf_server.py'
    restconf = Join-Path $Root 'servers\restconf_server.py'
    coreconf = Join-Path $Root 'servers\coreconf_server.py'
    client   = Join-Path $Root 'client\web.py'
}
$Order = @('netconf', 'restconf', 'coreconf', 'client')
$ResetTargets = @('netconf', 'restconf', 'coreconf')

# --- pid helpers -----------------------------------------------------------
function Get-PidFile([string]$Name) { Join-Path $Pids "$Name.pid" }

function Read-Pid([string]$Name) {
    $f = Get-PidFile $Name
    if (-not (Test-Path $f)) { return $null }
    $txt = (Get-Content $f -Raw).Trim()
    [int]$out = 0
    if ([int]::TryParse($txt, [ref]$out)) { return $out }
    return $null
}

function Test-ProcessRunning([int]$ProcessId) {
    if (-not $ProcessId) { return $false }
    $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    return [bool]$p
}

# --- verbs -----------------------------------------------------------------
function Start-Component([string]$Name) {
    New-Item -ItemType Directory -Force -Path $Pids, $Logs | Out-Null

    $existing = Read-Pid $Name
    if ($existing -and (Test-ProcessRunning $existing)) {
        Write-Host "[$Name] already running (pid $existing)"
        if ($Name -eq 'client') { Write-Host "[client] web interface: $ClientUrl" }
        return
    }

    $script = $Components[$Name]
    $log = Join-Path $Logs "$Name.log"
    $args = @()
    $args += $Py.Prefix
    $args += $script

    # Hidden background process; stdout+stderr to the per-component log.
    $proc = Start-Process -FilePath $Py.Exe -ArgumentList $args `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"

    Set-Content -Path (Get-PidFile $Name) -Value $proc.Id
    Write-Host "[$Name] started (pid $($proc.Id)), log: state\logs\$Name.log"
    if ($Name -eq 'client') { Write-Host "[client] web interface: $ClientUrl" }
}

function Stop-Component([string]$Name) {
    $procId = Read-Pid $Name
    if (-not $procId) {
        Write-Host "[$Name] no pid file; not running"
        return
    }
    if (Test-ProcessRunning $procId) {
        # /T also terminates child processes spawned by the component.
        & taskkill /PID $procId /T /F *> $null
        Start-Sleep -Milliseconds 300
        Write-Host "[$Name] stopped (pid $procId)"
    }
    else {
        Write-Host "[$Name] was not running (stale pid $procId)"
    }
    Remove-Item -Path (Get-PidFile $Name) -ErrorAction SilentlyContinue
}

function Show-Status {
    Write-Host 'component   state      pid'
    Write-Host '---------   --------   -----'
    foreach ($name in $Order) {
        $procId = Read-Pid $name
        if ($procId -and (Test-ProcessRunning $procId)) {
            Write-Host ("{0,-10}  running    {1}" -f $name, $procId)
        }
        else {
            Write-Host ("{0,-10}  stopped    -" -f $name)
        }
    }
}

function Reset-Datastore([string]$Name) {
    # Delegate to run.py; its datastore reset is pure cross-platform Python.
    $args = @()
    $args += $Py.Prefix
    $args += (Join-Path $Root 'run.py')
    $args += @('reset', $Name)
    & $Py.Exe @args
}

function Resolve-Targets([string]$t, [string[]]$universe) {
    if ($t -eq 'all') { return $universe }
    if ($universe -contains $t) { return @($t) }
    Write-Host "unknown target '$t'. choices: $($universe -join ', ') | all"
    exit 2
}

# --- dispatch --------------------------------------------------------------
switch ($Command) {
    'start' {
        foreach ($name in (Resolve-Targets $Target $Order)) {
            Start-Component $name
            Start-Sleep -Milliseconds 400   # let servers bind before client
        }
    }
    'stop' {
        $targets = Resolve-Targets $Target $Order
        [array]::Reverse($targets)
        foreach ($name in $targets) { Stop-Component $name }
    }
    'status' { Show-Status }
    'reset' {
        foreach ($name in (Resolve-Targets $Target $ResetTargets)) {
            Reset-Datastore $name
        }
    }
}
