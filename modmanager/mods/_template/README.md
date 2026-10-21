# 새 모드 만들기

1. 이 폴더를 `mods/<내_모드_id>/`로 복사하고 `mod.json`의 `id`를 폴더명과 같게 바꿉니다. `default_enabled`를 `true`로 바꾸거나 `cap2mod enable <id>`로 켭니다.
2. 바꾸고 싶은 내용에 따라:
   - **파일 교체/추가**: `files/` 아래에 게임 폴더와 같은 상대 경로로 넣습니다. 예) `files/Resource/FNT_STD.RES`, `files/scenario/scen21.des` + `scen21.gam` + `scen21.pic`(새 시나리오는 파일만 넣어도 목록에 나타남), `files/gameset/MYSET.SET`.
   - **텍스트 번역/수정**: `cap2mod dump-text "Resource\t_gmenu.res" text/t_gmenu.tsv`로 원문을 뽑고 3열을 고쳐 `text_patches: ["text/*.tsv"]`에 등록합니다. 줄 번호를 바꾸지 마세요.
   - **건물/제품명 등 1STD.SET 문자열**: `translat/*.tsv`에 `영어<TAB>번역`을 쓰고 `translat`에 등록합니다(한글 패치 모드처럼 프록시 DLL이 `TRANSLAT.RES`를 활성화해야 함).
   - **RES 안의 비트맵 한 장만 교체**: `cap2mod res ls "Resource\I_MENU.RES"`로 레코드명을 확인하고 `res_records`에 `{"file":..., "record":..., "from":"res/xxx.bin"}`을 추가합니다. 비트맵 형식은 `u16 w, u16 h, 8bpp 팔레트 인덱스(0xFF 투명)`입니다.
3. `cap2mod apply --dry-run`으로 어떤 파일이 바뀌는지 확인한 뒤 `apply`.
