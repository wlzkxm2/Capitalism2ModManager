# Capitalism2ModManager

Steam판 **Capitalism 2**(Cap2.exe, SDL2 빌드)용 모드 매니저입니다. Windows와 Linux(SteamOS/Steam Deck, Proton)에서 같은 코드로 동작합니다.

- 게임 폴더를 자동 탐지(또는 직접 지정)한 뒤 `mods/` 폴더의 모드를 적용합니다.
- 바꾸는 파일의 원본은 자동 백업되며 언제든 원본으로 복원할 수 있습니다.
- Python 3.8 이상 표준 라이브러리만 사용합니다(GUI는 tkinter).

## 내려받기

[Releases](../../releases)에서 받으세요.

| 파일 | 내용 |
|---|---|
| `Capitalism2ModManager-<버전>.zip` | 모드 매니저 + 한글 패치(`mods/korean_patch`) + 공급처 표시(`mods/supply_hint`) 모드 포함 |
| `korean_patch-<버전>.zip` | 한글 패치 모드만. 매니저의 `mods/` 폴더에 풀어 넣으면 됩니다 |
| `supply_hint-<버전>.zip` | 공급처 없는 구매 칸 표시 모드만. 매니저의 `mods/` 폴더에 풀어 넣으면 됩니다 |

## 빠른 사용법

- **Windows**: `cap2mod.bat` 더블클릭 → 게임 자동 인식 → 모드 선택 → **적용**
- **Linux / Steam Deck**: `./cap2mod.sh apply` (GUI는 `./cap2mod.sh gui`)

자세한 사용법, 모드 형식, 명령 목록은 [modmanager/README.md](modmanager/README.md)를 보세요.

## 한글 패치

- 게임 실행 파일(Cap2.exe)은 수정하지 않습니다. 프록시 `SDL2.dll`로 글자 출력 함수를 교체하고 메뉴·도움말·튜토리얼·시나리오 설명·건물/제품명을 번역합니다.
- 글꼴은 **나눔스퀘어라운드**(SIL Open Font License 1.1)를 동봉하며 시스템에 설치하지 않고 게임 프로세스 안에서만 등록합니다.
- Steam에서 "게임 파일 무결성 검사"를 하면 원본으로 돌아가므로 매니저에서 다시 **적용**하면 됩니다.

## 공급처 없는 구매 칸 표시 (supply_hint)

공장에 배치 계획을 적용했는데 공급처를 못 찾은 구매 칸에 사야 할 상품 이름과 "공급처 없음"을 표시합니다. 한글 패치와 함께 쓰면 모드 매니저가 두 프록시 DLL을 사슬로 연결합니다.
