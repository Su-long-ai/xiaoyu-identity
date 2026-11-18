param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O"
)

$ErrorActionPreference = "Stop"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
$Py = Join-Path $NekoRoot ".venv\Scripts\python.exe"

$GroupA = @(
    (Join-Path $NekoRoot "tests\unit\test_subject_archive.py")
)

$GroupB = @(
    (Join-Path $NekoRoot "tests\unit\test_cold_store.py"),
    (Join-Path $NekoRoot "tests\unit\test_memory_server_scoped_history_idempotency.py"),
    (Join-Path $NekoRoot "tests\unit\test_theater_forget_tombstone.py"),
    (Join-Path $NekoRoot "tests\unit\test_visit_forget.py"),
    (Join-Path $NekoRoot "tests\unit\test_visit_memory_bridge.py")
)

& $Py -m pytest -o 'addopts=' -p pytest_asyncio.plugin -q @GroupA
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Py -m pytest -o 'addopts=' -p pytest_asyncio.plugin -q @GroupB
exit $LASTEXITCODE
