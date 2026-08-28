# One-click stop of both local servers.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m server.cli stop @args
exit $LASTEXITCODE
