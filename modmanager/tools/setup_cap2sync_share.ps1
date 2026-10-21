# Capitalism 2 세이브 동기화 전용 계정과 공유 만들기 (관리자 PowerShell에서 실행)
#   - 로컬 계정 cap2sync (로그인 화면에는 숨김, 암호 만료 없음)
#   - 공유 \\<이 PC>\cap2saves → D:\steam\saves\capitalism2 (cap2sync만 읽기/쓰기)
param(
    [string]$Folder = "D:\steam\saves\capitalism2",
    [string]$ShareName = "cap2saves",
    [string]$UserName = "cap2sync"
)
$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "관리자 권한 PowerShell에서 실행하세요."
}
New-Item -ItemType Directory -Force $Folder | Out-Null

$pw = Read-Host "cap2sync 계정에 쓸 암호를 입력하세요(화면에 표시되지 않음)" -AsSecureString
if (Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue) {
    Set-LocalUser -Name $UserName -Password $pw -PasswordNeverExpires $true
    Write-Host "기존 계정 $UserName 의 암호를 바꿨습니다."
} else {
    New-LocalUser -Name $UserName -Password $pw -PasswordNeverExpires -AccountNeverExpires `
        -Description "Capitalism 2 save sync (SMB only)" | Out-Null
    Write-Host "계정 $UserName 을 만들었습니다."
}
# 로그인 화면에 표시하지 않음
$key = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList"
New-Item -Force $key | Out-Null
New-ItemProperty -Path $key -Name $UserName -Value 0 -PropertyType DWord -Force | Out-Null

# 폴더 권한: cap2sync 수정 권한(하위 포함)
$acl = Get-Acl $Folder
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($UserName, "Modify", "ContainerInherit,ObjectInherit", "None", "Allow")
$acl.AddAccessRule($rule)
Set-Acl $Folder $acl

# 공유: cap2sync만 전체 권한
if (Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue) { Remove-SmbShare -Name $ShareName -Force }
New-SmbShare -Name $ShareName -Path $Folder -FullAccess "$env:COMPUTERNAME\$UserName" | Out-Null
Get-SmbShareAccess -Name $ShareName | Format-Table -AutoSize
Write-Host "완료: \\$env:COMPUTERNAME\$ShareName → $Folder  (계정 $env:COMPUTERNAME\$UserName)"
