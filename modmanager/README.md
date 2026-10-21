# cap2mod — Capitalism 2 모드 매니저 (Windows / Linux)

Steam판 Capitalism 2(`Cap2.exe`, SDL2 빌드)에 모드를 적용·복원하는 도구입니다.
Python 3.8 이상 표준 라이브러리만 사용하며 Windows와 Linux(SteamOS/Steam Deck, Proton)에서 같은 코드로 동작합니다.

```
modmanager/
├─ cap2mod.py        매니저 본체 (CLI + tkinter GUI)
├─ cap2mod.bat       Windows 런처 (더블클릭 → GUI)
├─ cap2mod.sh        Linux 런처
├─ config.json       마지막으로 인식한 게임 경로(자동 생성)
└─ mods/
   ├─ enabled.json   모드 활성 상태(자동 생성)
   ├─ korean_patch/  한글 패치 모드
   └─ _template/     새 모드 템플릿(비활성)
```

## 1. 사용법

### Windows
1. `cap2mod.bat` 더블클릭 → GUI가 열리고 Steam 라이브러리에서 게임을 자동 탐지합니다. 못 찾으면 **찾기…**로 `Cap2.exe`가 있는 폴더를 지정합니다.
2. 모드 목록에서 더블클릭(또는 **활성/비활성 전환**)으로 켜고 끈 뒤 **적용**을 누릅니다.
3. **원본 복원**은 적용 전 상태로 되돌립니다. **상태/검증**은 Steam 무결성 검사 등으로 파일이 바뀌었는지 확인합니다.

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

## 4. 제한

- `Cap2.exe` 자체는 수정하지 않습니다. 코드 변경은 프록시 DLL(예: 한글 패치의 `SDL2.dll`) 방식으로만 가능하며, 같은 이름의 프록시 DLL은 한 모드만 제공할 수 있습니다.
- `exe_strings`는 Cap2.exe 빌드(해시)에 묶입니다.
- 매니저 상태는 게임 폴더의 `cap2mod/`에 있으므로 게임을 지우면 백업도 사라집니다(Steam이 원본을 다시 내려받으므로 복구는 가능).
