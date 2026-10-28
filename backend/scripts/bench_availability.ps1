<#
.SYNOPSIS
    Reproducible availability benchmark: cache-aside vs direct MySQL.

.DESCRIPTION
    Runs the same Locust availability workload against two already running API
    instances (one with CACHE_ENABLED=false, one with CACHE_ENABLED=true),
    records MySQL Com_select deltas, Redis cache hit/miss counters and writes a
    JSON summary plus Locust CSV files to docs/v2/performance.

    Start the instances first, for example:
        cd backend
        $env:CACHE_ENABLED='false'; fastapi run --port 8002
        $env:CACHE_ENABLED='true';  fastapi run --port 8003

.EXAMPLE
    cd backend
    pwsh scripts/bench_availability.ps1 -Users 10 -DurationSeconds 20
#>
param(
    [string]$NoCacheBase = "http://127.0.0.1:8002",
    [string]$CacheBase = "http://127.0.0.1:8003",
    [int]$Users = 10,
    [int]$SpawnRate = 5,
    [int]$DurationSeconds = 20,
    [string]$Seed = "../docs/v2/performance/seed.json",
    [string]$OutDir = "../docs/v2/performance",
    [string]$DbContainer = "full-stack-fastapi-template-master-db-1",
    [string]$RedisContainer = "full-stack-fastapi-template-master-redis-1"
)

$ErrorActionPreference = "Stop"
$backend = Split-Path -Parent $PSScriptRoot
$seedPath = Join-Path $backend $Seed
$outPath = Join-Path $backend $OutDir
New-Item -ItemType Directory -Force -Path $outPath | Out-Null

if (-not (Test-Path $seedPath)) {
    throw "Seed file not found: $seedPath. Run scripts/seed_benchmark.py first."
}

$dbUser = if ($env:MYSQL_USER) { $env:MYSQL_USER } else { "nexaslot" }
$dbPassword = if ($env:MYSQL_PASSWORD) { $env:MYSQL_PASSWORD } else { "changethis" }

function Get-ComSelect {
    $line = & docker exec $DbContainer mysql "-u$dbUser" "-p$dbPassword" -N -e "SHOW GLOBAL STATUS LIKE 'Com_select'"
    return [int](($line -split "`t")[1])
}

function Reset-CacheStats {
    & docker exec $RedisContainer redis-cli DEL nexaslot:stats:cache:hit nexaslot:stats:cache:miss | Out-Null
}

function Clear-AvailabilityCache {
    # Keep the MySQL buffer pool warm from the warmup run, but start the cache
    # measurement cold so the reported hit rate is not an artifact of warm keys.
    $keys = & docker exec $RedisContainer redis-cli --raw KEYS "nexaslot:availability:*"
    if ($keys) {
        & docker exec $RedisContainer redis-cli DEL $keys | Out-Null
    }
}

function Get-CacheStats {
    $raw = & docker exec $RedisContainer redis-cli MGET nexaslot:stats:cache:hit nexaslot:stats:cache:miss
    $hits = if ([string]::IsNullOrWhiteSpace($raw[0]) -or $raw[0] -eq "nil") { 0 } else { [int]$raw[0] }
    $misses = if ([string]::IsNullOrWhiteSpace($raw[1]) -or $raw[1] -eq "nil") { 0 } else { [int]$raw[1] }
    $total = $hits + $misses
    $rate = if ($total -gt 0) { [math]::Round($hits / $total, 4) } else { $null }
    return [pscustomobject]@{ hits = $hits; misses = $misses; hit_rate = $rate }
}

function Invoke-Locust {
    param([string]$BaseUrl, [string]$Label, [int]$UserCount, [int]$Spawn, [int]$Seconds, [switch]$Csv)

    $locustArgs = @(
        "run", "locust", "-f", "locust/locustfile.py", "--headless",
        "-u", "$UserCount", "-r", "$Spawn", "-t", "${Seconds}s",
        "--host", $BaseUrl, "--only-summary", "--loglevel", "WARNING"
    )
    if ($Csv) {
        $locustArgs += @("--csv", (Join-Path $outPath $Label))
    }
    Push-Location $backend
    try {
        & uv @locustArgs
        if ($LASTEXITCODE -ne 0) { throw "Locust failed with exit code $LASTEXITCODE" }
    }
    finally {
        Pop-Location
    }
}

function Measure-Target {
    param([string]$Label, [string]$BaseUrl)

    Write-Host "Warming up $Label ($BaseUrl)..."
    Invoke-Locust -BaseUrl $BaseUrl -Label "$Label-warmup" -UserCount 5 -Spawn 5 -Seconds 5
    Reset-CacheStats
    Clear-AvailabilityCache

    $before = Get-ComSelect
    Write-Host "Measuring ${Label}: $Users users, $DurationSeconds s..."
    Invoke-Locust -BaseUrl $BaseUrl -Label $Label -UserCount $Users -Spawn $SpawnRate -Seconds $DurationSeconds -Csv
    $after = Get-ComSelect
    $cache = Get-CacheStats

    $csv = Import-Csv (Join-Path $outPath ($Label + "_stats.csv"))
    $row = $csv | Where-Object { $_.Name -eq "/resources/[id]/availability" } | Select-Object -First 1
    if (-not $row) { throw "Availability row missing from $Label stats csv" }

    return [pscustomobject]@{
        label = $Label
        base_url = $BaseUrl
        users = $Users
        duration_seconds = $DurationSeconds
        requests = [int]$row."Request Count"
        failures = [int]$row."Failure Count"
        requests_per_second = [math]::Round([double]$row."Requests/s", 2)
        avg_ms = [int]$row."Average Response Time"
        p50_ms = [int]$row."50%"
        p95_ms = [int]$row."95%"
        p99_ms = [int]$row."99%"
        max_ms = [int]$row."Max Response Time"
        mysql_com_select = $after - $before
        cache_hits = $cache.hits
        cache_misses = $cache.misses
        cache_hit_rate = $cache.hit_rate
    }
}

$results = @(
    (Measure-Target -Label "availability-no-cache" -BaseUrl $NoCacheBase),
    (Measure-Target -Label "availability-cache" -BaseUrl $CacheBase)
)

$summary = [pscustomobject]@{
    generated_at = (Get-Date).ToString("o")
    environment = [pscustomobject]@{
        os = "Windows"
        mysql = "8.4.13 (docker, host port 3307)"
        redis = "7.4.12 (docker, host port 6380)"
        api_mode = "fastapi run (production, single worker per instance)"
        cache_measurement = "cold availability keys after a 5s DB-warmup run"
        seed = $Seed
        resources = 20
    }
    results = $results
}
$summary | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $outPath "benchmark-summary.json")
$results | Format-Table -AutoSize
Write-Host "Wrote $(Join-Path $outPath 'benchmark-summary.json')"
