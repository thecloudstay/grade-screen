# 휴대폰(USB 파일 전송 모드) Download\exp_inbox 목록 보기 / 복사
param([string]$mode = "list", [string]$name = "", [string]$dest = "")
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$sh = New-Object -ComObject Shell.Application
function Find-Inbox {
  foreach ($dev in $sh.NameSpace(17).Items()) {
    if (-not $dev.IsFolder) { continue }
    if ($dev.Path -notlike '*usb*') { continue }
    foreach ($st in $dev.GetFolder.Items()) {
      if (-not $st.IsFolder) { continue }
      $dl = $st.GetFolder.Items() | Where-Object { $_.Name -eq 'Download' } | Select-Object -First 1
      if (-not $dl) { continue }
      $ib = $dl.GetFolder.Items() | Where-Object { $_.Name -eq 'exp_inbox' } | Select-Object -First 1
      if ($ib) { return @($dev.Name, $ib, $dl) }
    }
  }
  return $null
}
$r = Find-Inbox
if (-not $r) { Write-Output "NODEV"; exit 0 }
$devName = $r[0]; $inbox = $r[1]; $dlItem = $r[2]
if ($mode -eq "push") {
  # 컴퓨터 파일($dest)을 휴대폰 Download 폴더로 복사(같은 이름 있으면 덮어씀)
  $dlItem.GetFolder.CopyHere($dest, 4 + 16 + 512 + 1024)
  Start-Sleep -Seconds 3
  Write-Output "PUSHED"
  exit 0
}
if ($mode -eq "list") {
  Write-Output ("DEV`t" + $devName)
  foreach ($f in $inbox.GetFolder.Items()) {
    if ($f.IsFolder) { continue }
    $size = $f.ExtendedProperty("System.Size")
    if (-not $size) { $size = $f.Size }
    Write-Output ("F`t" + $f.Name + "`t" + $size)
  }
  exit 0
}
if ($mode -eq "copy") {
  $item = $inbox.GetFolder.Items() | Where-Object { $_.Name -eq $name } | Select-Object -First 1
  if (-not $item) { Write-Output "MISSING"; exit 0 }
  $target = $sh.NameSpace($dest)
  $target.CopyHere($item, 4 + 16 + 512 + 1024)
  $base = [System.IO.Path]::GetFileNameWithoutExtension($name)
  $last = -1
  for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    $hit = Get-ChildItem -LiteralPath $dest -File | Where-Object { $_.Name -eq $name -or $_.BaseName -eq $name -or $_.BaseName -eq $base } | Select-Object -First 1
    if ($hit) {
      if ($hit.Length -gt 0 -and $hit.Length -eq $last) { Write-Output ("OK`t" + $hit.FullName); exit 0 }
      $last = $hit.Length
    }
  }
  Write-Output "TIMEOUT"
}
