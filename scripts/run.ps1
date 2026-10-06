param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Port

