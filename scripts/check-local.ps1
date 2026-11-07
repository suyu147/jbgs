$ErrorActionPreference = 'Continue'
$checks = @()
$services = @(
    @{Name='前端';Port=5175;Url='http://127.0.0.1:5175/'},
    @{Name='后端';Port=8010;Url='http://127.0.0.1:8010/health'},
    @{Name='MySQL';Port=3306;Url=$null},
    @{Name='Neo4j HTTP';Port=7474;Url=$null},
    @{Name='Neo4j Bolt';Port=7687;Url=$null}
)

foreach ($item in $services) {
    $listening = [bool](Get-NetTCPConnection -State Listen -LocalPort $item.Port -ErrorAction SilentlyContinue)
    $httpOk = $false
    if ($listening -and $item.Url) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $item.Url -TimeoutSec 8
            $httpOk = $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
        } catch {}
    }
    $checks += [pscustomobject]@{Service=$item.Name;Port=$item.Port;Listening=$listening;Http=$httpOk}
}

$checks | Format-Table -AutoSize
$failed = @($checks | Where-Object { -not $_.Listening -or ($_.Service -in @('前端','后端') -and -not $_.Http) })

try {
    $health = (Invoke-RestMethod -Uri 'http://127.0.0.1:8010/health' -TimeoutSec 8).data
    $health | ConvertTo-Json -Compress
} catch {
    Write-Warning '后端健康接口不可用。'
    $failed += [pscustomobject]@{Service='后端健康接口'}
}

try {
    $overview = (Invoke-RestMethod -Uri 'http://127.0.0.1:8010/api/v1/overview' -TimeoutSec 20).data
    $expected = [ordered]@{
        postingCount = @{Value=20014;Mode='exact'}
        skillCount = @{Value=3695;Mode='exact'}
        snapshotCount = @{Value=114257;Mode='exact'}
        timePeriodCount = @{Value=67;Mode='exact'}
        relationCount = @{Value=312233;Mode='minimum'}
    }
    $graphChecks = foreach ($name in $expected.Keys) {
        $actual = [long]$overview.$name
        $rule = $expected[$name]
        $passed = if ($rule.Mode -eq 'minimum') { $actual -ge $rule.Value } else { $actual -eq $rule.Value }
        $expectedLabel = if ($rule.Mode -eq 'minimum') { ">=$($rule.Value)" } else { [string]$rule.Value }
        [pscustomobject]@{Metric=$name;Expected=$expectedLabel;Actual=$actual;Passed=$passed}
    }
    $graphChecks | Format-Table -AutoSize
    if ($graphChecks | Where-Object { -not $_.Passed }) {
        $failed += [pscustomobject]@{Service='Neo4j 图谱计数'}
    }
    if ($overview.graphVersion -ne 'neo4j-20260814-v01') {
        Write-Warning "图谱版本不匹配：$($overview.graphVersion)"
        $failed += [pscustomobject]@{Service='Neo4j 图谱版本'}
    }
} catch {
    Write-Warning "图谱概览校验失败：$($_.Exception.Message)"
    $failed += [pscustomobject]@{Service='Neo4j 图谱概览'}
}

if ($failed.Count -gt 0) { exit 1 }
Write-Host '全部固定端口、健康接口和 20260814 图谱关键计数均通过。'
