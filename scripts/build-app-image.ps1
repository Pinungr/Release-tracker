<#
.SYNOPSIS
Build the PDS application image without Docker Compose.
.EXAMPLE
.\scripts\build-app-image.ps1 -Image pds-scheduler:2026.10 -ExportPath .\artifacts\pds-scheduler-2026.10.tar
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$Image = 'pds-scheduler:local',
    [string]$ExportPath,
    [switch]$NoCache
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is required. Install Docker and start its engine before running this script.'
}
& docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker engine is unavailable. Start Docker and retry.' }

# Resolve the export destination before building, and never overwrite a saved image.
$archivePath = $null
if ($ExportPath) {
    $archivePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ExportPath)
    if (Test-Path -LiteralPath $archivePath) { throw "Export destination already exists: $archivePath" }
    $archiveDirectory = Split-Path -Parent $archivePath
    if (-not (Test-Path -LiteralPath $archiveDirectory)) {
        New-Item -ItemType Directory -Path $archiveDirectory -Force | Out-Null
    }
}

$buildArguments = @('build', '--file', (Join-Path $projectRoot 'Dockerfile'), '--tag', $Image)
if ($NoCache) { $buildArguments += '--no-cache' }
$buildArguments += $projectRoot
& docker @buildArguments
if ($LASTEXITCODE -ne 0) { throw 'Application image build failed.' }
Write-Host "Built application image: $Image"

if ($archivePath) {
    & docker image save --output $archivePath $Image
    if ($LASTEXITCODE -ne 0) { throw 'Image export failed. The destination may contain an incomplete archive.' }
    Write-Host "Saved image archive: $archivePath"
    Write-Host 'Import on the target server with: docker image load --input <archive-path>'
}
Write-Host 'See README.md for running the image without Compose.'
