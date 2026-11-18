param([string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O")
$ErrorActionPreference = "Stop"
$py = Join-Path $NekoRoot ".venv\Scripts\python.exe"
$args = @(
  "-m", "pytest",
  (Join-Path $NekoRoot "tests\unit\test_fact_extraction_correction_rule.py"),
  (Join-Path $NekoRoot "tests\unit\test_persona_refine_apply.py"),
  "-q", "-o", "asyncio_mode=auto"
)
& $py @args
exit $LASTEXITCODE