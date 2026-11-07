$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $packageRoot 'backend\.env.local'
$demoRoot = Join-Path $packageRoot 'demo-data'
$sampleRoot = if (Test-Path -LiteralPath $demoRoot) { (Get-ChildItem -LiteralPath $demoRoot -Directory | Select-Object -First 1).FullName } else { '' }
$apiBase = 'http://127.0.0.1:8010/api/v1'

if (-not (Test-Path -LiteralPath $envFile) -or [string]::IsNullOrWhiteSpace($sampleRoot) -or -not (Test-Path -LiteralPath $sampleRoot)) { return }

$settings = @{}
Get-Content -LiteralPath $envFile -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $settings[$matches[1]] = $matches[2] }
}
$username = if ($settings.ENTERPRISE_USERNAME) { $settings.ENTERPRISE_USERNAME } else { 'enterprise' }
$password = if ($settings.ENTERPRISE_PASSWORD) { $settings.ENTERPRISE_PASSWORD } else { '123456' }
$loginBody = @{ username = $username; password = $password; portal = 'enterprise' } | ConvertTo-Json
$login = Invoke-RestMethod -Method Post -Uri "$apiBase/auth/login" -ContentType 'application/json; charset=utf-8' -Body $loginBody -TimeoutSec 15
$headers = @{ Authorization = "Bearer $($login.data.accessToken)" }
$current = Invoke-RestMethod -Method Get -Uri "$apiBase/enterprise/resumes?limit=500" -Headers $headers -TimeoutSec 20
$existingNames = @($current.data.items | ForEach-Object { $_.fileName })
$pending = @(Get-ChildItem -LiteralPath $sampleRoot -File -Filter '*.txt' | Where-Object { $_.Name -notin $existingNames })
if ($pending.Count -eq 0) {
    Write-Host 'Enterprise demo resumes are ready.'
    return
}

Add-Type -AssemblyName System.Net.Http
$client = [System.Net.Http.HttpClient]::new()
$multipart = [System.Net.Http.MultipartFormDataContent]::new()
$streams = [System.Collections.Generic.List[System.IDisposable]]::new()
try {
    $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $login.data.accessToken)
    foreach ($file in $pending) {
        $stream = [System.IO.File]::OpenRead($file.FullName)
        $streams.Add($stream)
        $content = [System.Net.Http.StreamContent]::new($stream)
        $content.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new('text/plain')
        $multipart.Add($content, 'files', $file.Name)
    }
    $response = $client.PostAsync("$apiBase/enterprise/resumes", $multipart).GetAwaiter().GetResult()
    if (-not $response.IsSuccessStatusCode) {
        $detail = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        throw "HTTP $([int]$response.StatusCode): $detail"
    }
    $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    Write-Host "Added $($payload.data.accepted) enterprise demo resumes."
} finally {
    foreach ($stream in $streams) { $stream.Dispose() }
    $multipart.Dispose()
    $client.Dispose()
}
