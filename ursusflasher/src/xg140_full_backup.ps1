param(
  [string]$RouterIP = "192.168.1.1"
)
$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resultsDir = Join-Path $PSScriptRoot "..\results"
New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null
$root = Join-Path (Resolve-Path $resultsDir) "xg140-full-backup-$stamp"
New-Item -ItemType Directory -Force -Path $root | Out-Null

$sshExe = (Get-Command ssh.exe -ErrorAction Stop).Source
$sshCommon = @('-o','ConnectTimeout=5','-o','StrictHostKeyChecking=accept-new',("root@{0}" -f $RouterIP))

function SshText([string]$cmd) {
  $out = & $sshExe @sshCommon $cmd 2>&1
  if ($LASTEXITCODE -ne 0) { throw "SSH command failed: $cmd`n$($out -join "`n")" }
  return ($out -join "`n")
}

Write-Host "Checking OpenWrt initramfs at $RouterIP ..."
$board = SshText 'ubus call system board 2>/dev/null || true'
$mtd = SshText 'cat /proc/mtd'
$dmesg = SshText 'dmesg'
$board | Set-Content -Encoding UTF8 (Join-Path $root 'system-board.txt')
$mtd | Set-Content -Encoding UTF8 (Join-Path $root 'proc-mtd.txt')
$dmesg | Set-Content -Encoding UTF8 (Join-Path $root 'dmesg.txt')

$parts = @()
foreach ($line in ($mtd -split "`n")) {
  if ($line -match '^mtd(\d+):\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+"([^"]+)"') {
    $parts += [pscustomobject]@{
      Index=[int]$Matches[1]
      Size=[Convert]::ToInt64($Matches[2],16)
      Erase=[Convert]::ToInt64($Matches[3],16)
      Name=$Matches[4]
    }
  }
}
if ($parts.Count -eq 0) { throw 'No MTD partitions found in /proc/mtd' }

$manifest = @()
foreach ($p in $parts) {
  $safe = ($p.Name -replace '[^A-Za-z0-9._-]','_')
  $gz = Join-Path $root ("mtd{0}_{1}.bin.gz" -f $p.Index,$safe)
  Write-Host ("Backing up mtd{0} {1} size=0x{2:x}" -f $p.Index,$p.Name,$p.Size)

  $remoteHash = (SshText ("sha256sum /dev/mtd{0}" -f $p.Index)).Split()[0]

  # Windows PowerShell 5.1-safe binary streaming: let cmd.exe perform raw stdout redirection.
  # PowerShell's own redirection can transcode native stdout, so do not use it for MTD bytes.
  $quotedSsh = '"' + $sshExe + '"'
  $remoteCmd = "gzip -1 < /dev/mtd$($p.Index)"
  $cmdLine = ('{0} -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new root@{1} "{2}" > "{3}"' -f $quotedSsh,$RouterIP,$remoteCmd,$gz)
  & $env:ComSpec /d /s /c $cmdLine
  if ($LASTEXITCODE -ne 0) { throw "Backup transfer failed for mtd$($p.Index)" }
  if (-not (Test-Path $gz)) { throw "Backup file was not created for mtd$($p.Index)" }

  $in = [System.IO.File]::OpenRead($gz)
  $gzs = New-Object System.IO.Compression.GZipStream($in,[System.IO.Compression.CompressionMode]::Decompress)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $buf = New-Object byte[] (1024*1024)
  [Int64]$rawSize = 0
  try {
    while (($n = $gzs.Read($buf,0,$buf.Length)) -gt 0) {
      [void]$sha.TransformBlock($buf,0,$n,$null,0)
      $rawSize += $n
    }
    [void]$sha.TransformFinalBlock([byte[]]::new(0),0,0)
    $localHash = -join ($sha.Hash | ForEach-Object { $_.ToString('x2') })
  } finally {
    $sha.Dispose(); $gzs.Dispose(); $in.Dispose()
  }

  if ($rawSize -ne $p.Size) { throw "Size mismatch mtd$($p.Index): got $rawSize expected $($p.Size)" }
  if ($localHash -ne $remoteHash) { throw "SHA256 mismatch mtd$($p.Index): remote=$remoteHash local=$localHash" }
  $manifest += ("{0}  mtd{1}_{2}.bin  size=0x{3:x} erase=0x{4:x}" -f $localHash,$p.Index,$safe,$p.Size,$p.Erase)
}

$manifest | Set-Content -Encoding ASCII (Join-Path $root 'SHA256SUMS.txt')
@(
  'Nokia/Bell XG-140G-MD full read-only backup',
  "Router: $RouterIP",
  "Partitions: $($parts.Count)",
  'Source: OpenWrt initramfs /dev/mtd*',
  'No NAND write command is issued by this script.'
) | Set-Content -Encoding UTF8 (Join-Path $root 'REPORT.txt')
Write-Host "Backup complete: $root"
