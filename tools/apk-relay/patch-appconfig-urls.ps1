param(
    [Parameter(Mandatory = $true)]
    [string]$DataRoot
)

$replacements = @{
    'https://dev-platform.idoltime.games' = 'http://127.0.0.1:000000000000008080'
    'https://pxapi.jhdwxp.com' = 'http://127.0.0.1:0008080'
    'https://pxi.qkdaxdd.com' = 'http://127.0.0.1:008080'
    'https://px-api.zkifae.cn' = 'http://127.0.0.1:0008080'
    'https://dev-svrlist.idoltime.games' = 'http://127.0.0.1:00000000000008080'
}

function Replace-Bytes([byte[]]$source, [byte[]]$old, [byte[]]$new) {
    $count = 0
    for ($i = 0; $i -le $source.Length - $old.Length; $i++) {
        $match = $true
        for ($j = 0; $j -lt $old.Length; $j++) {
            if ($source[$i + $j] -ne $old[$j]) {
                $match = $false
                break
            }
        }
        if ($match) {
            [Array]::Copy($new, 0, $source, $i, $new.Length)
            $count++
            $i += $old.Length - 1
        }
    }
    return $count
}

$changed = 0
foreach ($file in Get-ChildItem -LiteralPath $DataRoot -Recurse -File) {
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    $fileCount = 0
    foreach ($entry in $replacements.GetEnumerator()) {
        $old = [Text.Encoding]::ASCII.GetBytes($entry.Key)
        $new = [Text.Encoding]::ASCII.GetBytes($entry.Value)
        if ($old.Length -ne $new.Length) {
            throw "replacement length mismatch: $($entry.Key)"
        }
        $fileCount += Replace-Bytes $bytes $old $new
    }
    if ($fileCount -gt 0) {
        [IO.File]::WriteAllBytes($file.FullName, $bytes)
        $changed += $fileCount
        Write-Output "$($file.FullName): $fileCount replacements"
    }
}
Write-Output "total replacements: $changed"
