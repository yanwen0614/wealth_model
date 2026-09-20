<#
.SYNOPSIS
  散户友好模型后台训练启动器

.DESCRIPTION
  在后台启动 train_retail.py 训练，输出重定向到日志文件。
  模拟 Linux tmux 的分离运行效果。

  监控方法：
    Get-Content -Wait logs/retail_relative/run_*/training.log
    Import-Csv logs/retail_relative/run_*/epoch_metrics.csv

.USAGE
  .\scripts\launch_retail_train.ps1
  .\scripts\launch_retail_train.ps1 -Epochs 80 -BatchSize 256
  .\scripts\launch_retail_train.ps1 -Smoke

.PARAMETER Epochs
  训练轮数（默认 50）
.PARAMETER BatchSize
  批次大小（默认 256）
.PARAMETER LearningRate
  学习率（默认 3e-4）
.PARAMETER Normalize
  归一化模式（默认 relative）
.PARAMETER Smoke
  冒烟模式（20股 1轮）
#>

param(
    [int]$Epochs = 50,
    [int]$BatchSize = 256,
    [float]$LearningRate = 3e-4,
    [string]$Normalize = "relative",
    [switch]$Smoke = $false
)

$ProjectDir = Split-Path -Parent $PSScriptRoot | Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ProjectDir) { $ProjectDir = "D:\code\cnn_full_20260905\cnn" }
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogDir = "$ProjectDir\logs\run_retail_$Timestamp"
$Null = New-Item -ItemType Directory -Path $LogDir -Force
$LogFile = "$LogDir\launch.log"
$StdoutFile = "$LogDir\training_stdout.log"

$CmdArgs = @(
    "run", "--project", ".",
    "python", "train_retail.py",
    "--epochs", $Epochs,
    "--batch_size", $BatchSize,
    "--lr", $LearningRate,
    "--normalize", $Normalize,
    "--num_workers", "0"
)

if ($Smoke) {
    $CmdArgs += "--smoke"
}

$CmdLine = "uv $($CmdArgs -join ' ')"

# 写启动日志
@"
========================================
  散户模型训练启动
  启动时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  日志目录: $LogDir
  命令行:   $CmdLine
========================================
"@ | Out-File -FilePath $LogFile -Encoding utf8
"日志: $LogFile" | Write-Host -ForegroundColor Cyan

# 使用 Start-Process -NoNewWindow 实现后台运行（不阻塞当前 shell）
$Process = Start-Process -FilePath "uv" -ArgumentList $CmdArgs `
    -NoNewWindow -PassThru -RedirectStandardOutput $StdoutFile

# 记录 PID
"PID: $($Process.Id)" | Out-File -FilePath $LogFile -Encoding utf8 -Append

@"

PID: $($Process.Id)
输出日志: $StdoutFile

监控命令:
  # 查看实时输出
  Get-Content -Wait '$StdoutFile'

  # 查看训练日志
  Get-Content -Wait '$LogDir\training.log'

  # 查看指标 CSV
  Import-Csv '$LogDir\epoch_metrics.csv'

  # 停止训练
  Stop-Process -Id $($Process.Id)
"@ | Write-Host -ForegroundColor Green

# 等 5 秒确认进程启动
Start-Sleep -Seconds 5
if (Get-Process -Id $Process.Id -ErrorAction SilentlyContinue) {
    "✓ 训练进程已启动 (PID: $($Process.Id))" | Write-Host -ForegroundColor Green
} else {
    "✗ 训练进程未能启动，请检查 $StdoutFile" | Write-Host -ForegroundColor Red
}
