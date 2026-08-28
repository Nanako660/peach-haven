# Generic passthrough to the server management CLI.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m server.cli @args
exit $LASTEXITCODE
