# cap2mod — Capitalism 2 모드 매니저 (Windows / Linux)

Steam판 Capitalism 2(`Cap2.exe`, SDL2 빌드)에 모드를 적용·복원하는 도구입니다.
Python 3.8 이상 표준 라이브러리만 사용하며 Windows와 Linux(SteamOS/Steam Deck, Proton)에서 같은 코드로 동작합니다.

```
modmanager/
├─ Cap2ModManager.exe  Windows 화면 (권장, 작업은 cap2mod.py에 맡김)
├─ cap2mod.py        매니저 본체 (CLI + tkinter GUI)
├─ cap2mod.bat       Windows 런처 (더블클릭 → tkinter GUI)
├─ win/              Cap2ModManager.exe 소스 (C# WinForms, .NET Framework 4.8)
├─ cap2mod.sh        Linux 런처
├─ config.json       마지막으로 인식한 게임 경로(자동 생성)
└─ mods/
   ├─ enabled.json   모드 활성 상태(자동 생성)
   ├─ korean_patch/  한글 패치 모드
   ├─ supply_hint/   공급처 없는 구매 칸 표시 모드
   ├─ hires/         고해상도 모드(기본 꺼짐)
   └─ _template/     새 모드 템플릿(비활성)
```

## 1. 사용법

### Windows
1. `Cap2ModManager.exe` 더블클릭 → Steam 라이브러리에서 게임을 자동 탐지합니다. 못 찾으면 **찾기…**로 `Cap2.exe`를 지정합니다.
   - Windows 10/11에 기본으로 들어 있는 .NET Framework 4.8로 동작하며, Python 3.8 이상이 설치돼 있어야 합니다(설치본을 자동으로 찾음).
   - exe는 `cap2mod.py`와 같은 폴더에 두세요.
2. **모드** 탭에서 체크박스로 켜고 끈 뒤 **적용**을 누릅니다.
3. **원본 복원**은 적용 전 상태로 되돌립니다. **적용 상태 검증**은 Steam 무결성 검사 등으로 파일이 바뀌었는지 확인합니다.
4. **세이브 동기화** 탭에서 동기화 폴더 설정, 지금 동기화, Steam 실행 옵션 복사를 할 수 있습니다.

`cap2mod.bat`(tkinter 화면)도 그대로 쓸 수 있습니다. exe 빌드: `dotnet build modmanager/win -c Release` → `modmanager/win/bin/Release/Cap2ModManager.exe`.

명령줄:
```bat
cap2mod.bat detect                 :: 게임 폴더 탐지
cap2mod.bat list                   :: 모드 목록
cap2mod.bat enable korean_patch    :: 활성화 / disable 비활성화
cap2mod.bat apply [--dry-run]      :: 활성 모드 적용(원본 자동 백업)
cap2mod.bat restore                :: 원본 복원
cap2mod.bat verify                 :: 적용 상태 해시 검증
cap2mod.bat status                 :: 게임/적용 상태
cap2mod.bat --game "D:\Games\Capitalism 2" apply   :: 경로 직접 지정
```

### Linux / SteamOS(Steam Deck)
데스크톱 모드에서 터미널(Konsole)을 열고:
```sh
chmod +x cap2mod.sh
./cap2mod.sh detect        # ~/.steam, ~/.local/share/Steam, Flatpak, SD카드(/run/media/*) 라이브러리 탐색
./cap2mod.sh apply
./cap2mod.sh gui           # python3-tk 가 있으면 GUI
```
- 게임은 Proton으로 실행되는 Windows 실행 파일이므로 모드도 Windows용 그대로(프록시 DLL 포함) 적용됩니다.
- 게임은 `RESOURCE\T_GMENU.RES`처럼 대소문자가 다른 경로로 파일을 열고 Wine이 대소문자를 무시해 매핑합니다. 매니저는 **이미 존재하는 실제 파일명을 대소문자 무시로 찾아 덮어쓰므로** Linux에서 `Resource/t_gmenu.res`와 `RESOURCE/T_GMENU.RES`가 따로 생기는 문제가 없습니다.
- 사용자 데이터(CONFIG.DAT, SAVE)는 Proton 프리픽스 `steamapps/compatdata/638200/pfx/drive_c/users/steamuser/Documents/My Games/Capitalism 2`에 있습니다(`status`가 표시).
- 한글 패치 모드는 글꼴(Noto Sans KR, SIL OFL 1.1)을 동봉해 프로세스 전용으로 등록하므로 시스템 한글 글꼴을 따로 설치할 필요가 없습니다.

## 2. 동작 방식

| 단계 | 내용 |
|---|---|
| 게임 인식 | Steam 레지스트리/`libraryfolders.vdf`/기본 경로에서 `steamapps/common/Capitalism 2/Cap2.exe` 탐색, 필수 폴더(Resource, gameset, firm …) 확인, `Cap2.exe` SHA-256으로 빌드 식별 |
| 백업 | 바꾸는 파일의 원본을 `<게임>/cap2mod/backup/`에 1회 보존, 해시를 `vanilla.json`에 기록 |
| 적용 | 활성 모드를 `priority` 오름차순으로 합쳐 파일을 씀. 같은 파일을 여러 모드가 바꾸면 **priority가 큰 모드가 이김**(충돌은 로그에 표시) |
| 기록 | `<게임>/cap2mod/manifest.json`에 변경 파일·해시·생성 파일을 기록. 재적용 시 먼저 자동 복원(멱등) |
| 복원 | manifest 기준으로 백업 복원, 새로 만든 파일 삭제, 프록시 DLL이 보존한 `*_org.dll` 삭제 |

Steam에서 "게임 파일 무결성 검사"를 하면 Steam이 원본을 다시 내려받습니다. 이때 `verify`가 "원본으로 되돌아감"을 보고하며, `apply`를 다시 실행하면 됩니다.

## 3. 모드 형식 (`mods/<id>/mod.json`)

```json
{
  "id": "my_mod",                    // 폴더명과 같게. 영숫자 _ - . 만
  "name": "표시 이름", "version": "1.0.0", "author": "", "description": "",
  "priority": 100,                   // 적용 순서. 큰 값이 나중에 적용되어 우선
  "default_enabled": true,
  "requires": [], "conflicts": [],   // 다른 모드 id
  "requires_exe_sha256": [],         // 특정 Cap2.exe 빌드 전용이면 해시 나열(exe 문자열 패치는 불일치 시 거부)
  "encoding": "cp949",               // 텍스트 생성물 인코딩
  "ksx1001_only": true,              // 0xA1~0xFE 쌍만 허용(0x80~0x8F는 게임 아이콘 코드)

  "files": "files",                  // ① 오버레이: files/ 아래 경로를 게임 폴더에 그대로 덮어씀
  "proxy_dll": {"file": "SDL2.dll", "original_as": "SDL2_org.dll"},   // ② 원본 DLL을 이 이름으로 보존 후 교체
  "res_records": [                   // ③ *.RES/*.SET 안의 레코드 교체(ResourceIdx 형식)
    {"file": "Resource/I_MENU.RES", "record": "RETWORD1", "from": "res/retword1.bin", "add": false}
  ],
  "text_patches": ["text/*.tsv"],    // ④ 파일<TAB>줄번호<TAB>번역  (.des 는 줄번호 1 = 본문 전체)
  "translat": ["translat/*.tsv"],    // ⑤ 영어<TAB>번역 → Resource/TRANSLAT.RES (영어|번역~ 형식, '|' '~' 금지)
  "exe_strings": ["exe_strings.tsv"],// ⑥ 0x주소<TAB>영어<TAB>번역 → cap2kr_exe.txt (원문 바이트 길이 이하만, 프록시 DLL 필요)
  "exe_strings_out": "cap2kr_exe.txt"
}
```

- ①은 게임이 모든 파일을 **게임 폴더 기준 상대 경로**로 열기 때문에 그대로 동작합니다. 새 파일 추가도 가능하며, `gameset/*.SET`, `firm/*.BLD`, `scenario/*.des`(+`.gam`/`.pic`), `tutorial/*.des`는 게임이 와일드카드로 열거하므로 **파일을 넣기만 해도 목록에 추가**됩니다.
- ④는 게임의 텍스트 로더가 줄 번호로 인덱싱하므로 줄 수·순서·`[TAG]`·끝의 `|`를 매니저가 유지합니다. 원문 줄 번호는 `cap2mod dump-text "Resource\t_gmenu.res" out.tsv`로 뽑을 수 있습니다.
- ③의 레코드 목록은 `cap2mod res ls "Resource\I_MENU.RES"`, 추출은 `cap2mod res extract <파일> --record NAME --out dir`.
- ④⑤⑥은 모든 활성 모드의 항목을 병합해 하나의 결과를 만듭니다(같은 키는 priority가 큰 모드 우선).
- ②를 여러 모드가 같은 DLL로 쓰면 매니저가 **프록시 사슬**로 연결합니다. 각 프록시 DLL은 내보내기를 `SDL2_org.함수`로 포워딩해 두기만 하면 되고, 매니저가 포워더 문자열의 모듈 이름을 같은 길이의 다음 고리 이름으로 바꿔 씁니다.
  예) 한글 패치(100) + supply_hint(200) → `SDL2.dll`(supply_hint) → `SDL2_c01.dll`(한글 패치) → `SDL2_org.dll`(원본). 게임이 SDL 함수를 가져올 때 사슬의 DLL이 모두 로드되어 각자의 `DllMain`이 실행됩니다.

## 4. 제한

- `Cap2.exe` 자체는 수정하지 않습니다. 코드 변경은 프록시 DLL(예: 한글 패치의 `SDL2.dll`) 방식으로만 가능합니다. 같은 DLL의 프록시는 사슬로 연결되므로 여러 모드가 각자 훅을 걸 수 있지만, 같은 코드 위치에 훅을 거는 모드끼리는 충돌할 수 있습니다.
- `exe_strings`는 Cap2.exe 빌드(해시)에 묶입니다.
- 매니저 상태는 게임 폴더의 `cap2mod/`에 있으므로 게임을 지우면 백업도 사라집니다(Steam이 원본을 다시 내려받으므로 복구는 가능).

## 세이브 자동 동기화 (Steam 클라우드 대체)

Capitalism 2는 Steam 클라우드를 지원하지 않습니다. 대신 Steam 실행 옵션으로 매니저를 거쳐 게임을 켜면, 게임 시작 직전에 최신 세이브를 받고 게임 종료 직후 바뀐 세이브를 올립니다. 동기화 대상은 세이브 폴더(`Documents/My Games/Capitalism 2/SAVE`, Proton은 `compatdata/638200/pfx/.../SAVE`)이고 기기별 설정(`CONFIG.DAT`)은 건드리지 않습니다.

1. 기기마다 한 번: `cap2mod sync-setup <공유 폴더>` — 폴더를 기억하고 첫 동기화를 한 뒤 실행 옵션 줄을 출력합니다.
2. Steam → 라이브러리 → Capitalism 2 → 속성 → 일반 → 실행 옵션에 출력된 줄을 넣습니다.
   - Windows 예: `"C:\...\pythonw.exe" "C:\...\cap2mod.py" run -- %command%`
   - Steam Deck 예: `python3 /home/deck/Capitalism2ModManager/cap2mod.py run -- %command%`
3. 수동 실행: `cap2mod sync` (양방향), `cap2mod sync --direction pull|push`

- 비교 방식: 기기마다 마지막 동기화 상태를 `sync_base.json`에 남겨 3-방향으로 비교합니다. 한쪽만 바뀐 파일은 그쪽으로 맞추고, 지운 파일은 지운 채로 맞춥니다.
- 두 기기에서 같은 세이브를 따로 바꾸면 수정 시각이 늦은 쪽을 남기고, 다른 쪽은 공유 폴더 `backup/<시각>_<기기>_.../`에 보관합니다. 지워진 파일도 같은 곳에 보관합니다.
- 게임 실행 중에는 공유 폴더에 `lock.json`을 남겨, 다른 기기에서 동시에 실행하면 `sync.log`에 경고를 남깁니다.
- 공유 폴더에 접근할 수 없으면 동기화를 건너뛰고 게임은 그대로 실행됩니다. 다음 실행 때 다시 맞춥니다.
- 기록: 매니저 폴더의 `sync.log`

### 마운트할 수 없는 기기(Android 위 리눅스 등): `smb://`

공유 폴더를 마운트할 수 없으면 `smbclient`로 직접 주고받습니다.

1. Windows PC(관리자 PowerShell): `tools/setup_cap2sync_share.ps1` — 전용 로컬 계정 `cap2sync`와 공유 `cap2saves`(세이브 폴더만)를 만듭니다.
2. 기기에서 인증 파일(권한 600):
   ```
   printf 'username=cap2sync
password=%s
domain=<PC 이름>
' '<암호>' > ~/.cap2sync_smb && chmod 600 ~/.cap2sync_smb
   ```
3. `python3 cap2mod.py sync-setup smb://<PC 주소>/cap2saves` (다른 인증 파일은 `--auth`)

원격 세이브를 `sync_cache/`로 받아 같은 방식으로 비교한 뒤 바뀐 파일만 다시 올립니다.

