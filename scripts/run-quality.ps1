param(
    [switch]$SkipTests,
    [switch]$SkipOcr,
    [switch]$SkipEvidenceRefresh
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Python = Join-Path $Backend '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw "Backend virtual environment is missing: $Python" }

$qualityRoot = Join-Path $Backend 'quality_artifacts\coverage-20260825'
New-Item -ItemType Directory -Force $qualityRoot | Out-Null

Push-Location $Backend
try {
    if (-not $SkipTests) {
        & $Python -m coverage erase
        & $Python -m coverage run --branch --source=app -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
    }
    & $Python -m coverage json -o (Join-Path $qualityRoot 'coverage.json')
    & $Python -m coverage report
    $env:PYTHONPATH = $Backend
    $governedData = Join-Path $Root '各类所需数据'
    if (-not (Test-Path -LiteralPath $governedData)) {
        $exampleRoot = Split-Path -Parent (Split-Path -Parent $Root)
        $governedData = Join-Path $exampleRoot '各类所需数据'
    }
    if (-not $SkipEvidenceRefresh -and (Test-Path $governedData)) {
        & $Python scripts\build_competition_evidence.py
        if ($LASTEXITCODE -ne 0) { throw 'Competition evidence generation failed.' }
    }
    & $Python scripts\build_benchmark_v04.py
    if ($LASTEXITCODE -ne 0) { throw 'Strengthened acceptance benchmark failed.' }
    & $Python scripts\evaluate_trend_ablation.py
    if ($LASTEXITCODE -ne 0) { throw 'Trend ablation failed.' }
    if (-not $SkipOcr) {
        & $Python scripts\evaluate_scanned_resume_ocr.py
        if ($LASTEXITCODE -ne 0) { throw 'Scanned resume OCR benchmark failed.' }
    }
    & $Python scripts\generate_quality_artifacts.py `
        --coverage-file (Join-Path $qualityRoot 'coverage.json')
    if ($LASTEXITCODE -ne 0) { throw 'Neo4j integrity checks failed.' }
}
finally {
    Pop-Location
}

Write-Output "Quality artifacts and strengthened benchmarks written under $qualityRoot and 应用数据\quality"
