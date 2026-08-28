# One-click start of both local servers (HTTP SDK + game TCP).
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m server.cli start @args
exit $LASTEXITCODE
