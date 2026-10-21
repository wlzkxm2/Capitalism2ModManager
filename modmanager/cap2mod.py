#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cap2mod — Capitalism 2 (Steam, Cap2.exe SDL2 빌드) 모드 매니저
=============================================================

Windows / Linux(SteamOS·Proton) 공용. Python 3.8+ 표준 라이브러리만 사용.

동작 개요
  1. 원본 게임 폴더를 인식(자동 탐지 또는 --game 지정)하고 Cap2.exe 해시로 빌드를 식별한다.
  2. 매니저 폴더의 mods/<id>/mod.json 을 읽어 활성 모드를 priority 순으로 합친다.
  3. 게임 폴더에 적용하기 전 원본을 <game>/cap2mod/backup/ 에 백업하고 manifest.json 에 기록한다.
  4. restore 로 manifest 기준 원본 복원(새로 만든 파일은 삭제).

게임 구조 근거(REA/Ghidra 분석, analysis/MODDING_REPORT.md 참조)
  - 모든 파일은 File::file_open(0x542ee0)에서 "" + 상대경로로 CreateFileA → 게임 폴더 기준 상대 경로 오버레이가 그대로 먹는다.
  - GAMESET\\*.SET, FIRM\\*.BLD, <dir>\\*.DES 는 FindFirstFileA 로 열거 → 파일을 추가하는 것만으로 콘텐츠가 늘어난다.
  - *.RES / *.SET 는 ResourceIdx(Resx.cpp) 형식: s16 count, (count+1)*13B {char name[9]; s32 offset} 인덱스 + 데이터.
  - 텍스트 .res 는 Txtres.cpp 가 줄 번호로 인덱싱 → 줄 수/순서를 유지하며 치환.
  - 사용자 데이터(CONFIG.DAT, SAVE\\)는 Documents\\My Games\\Capitalism 2 (0x4114b0) → 게임 폴더 밖, 모드가 건드리지 않음.
"""
import argparse
import fnmatch
import glob
import hashlib
import io
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import time

VERSION = "1.0.0"
APP_ID = "638200"                       # Steam appmanifest_638200.acf ("Capitalism 2")
GAME_EXE = "Cap2.exe"
KNOWN_EXE_SHA256 = {
    "35aabdbde513681553cfdc8e3a913ec9dcd3de22532bb03c1b372103649759d8": "Steam SDL2 빌드 v1.20 (2026-10 분석 기준)",
}
# 원본 게임의 필수 디렉터리(인식 검증용; 대소문자 무시)
REQUIRED_DIRS = ["Resource", "gameset", "firm", "firmif", "image", "scenario", "tutorial"]
STATE_DIRNAME = "cap2mod"               # <game>/cap2mod/{manifest.json, backup/, vanilla.json}

HERE = os.path.dirname(os.path.abspath(__file__))
MODS_DIR = os.path.join(HERE, "mods")
CONFIG_PATH = os.path.join(HERE, "config.json")
IS_WIN = platform.system() == "Windows"


# ----------------------------------------------------------------------------
# 콘솔/로그
# ----------------------------------------------------------------------------
def _setup_console():
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_LOG_SINK = [None]   # GUI가 가로채기 위한 훅


def log(msg=""):
    if _LOG_SINK[0]:
        _LOG_SINK[0](str(msg))
    else:
        print(msg)


def warn(msg):
    log("경고: " + str(msg))


class ModError(Exception):
    pass


# ----------------------------------------------------------------------------
# 유틸
# ----------------------------------------------------------------------------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def norm_rel(rel):
    """모드/TSV 안의 상대 경로를 '/' 구분자로 정규화."""
    rel = rel.replace("\\", "/").strip("/")
    while rel.startswith("./"):
        rel = rel[2:]
    if rel.startswith("../") or "/../" in rel or os.path.isabs(rel):
        raise ModError("게임 폴더 밖을 가리키는 경로: %s" % rel)
    return rel


def resolve_case(root, rel, create_dirs=False):
    """
    대소문자 무시로 실제 경로를 찾는다(Linux에서 중요: 게임은 Windows 규약 'RESOURCE\\X.RES'로 열고
    Proton/Wine이 대소문자 무시로 매핑하므로, 우리는 이미 존재하는 실제 이름을 재사용해야 한다).
    반환: (절대경로, 존재여부)
    """
    cur = root
    parts = norm_rel(rel).split("/")
    for i, part in enumerate(parts):
        last = (i == len(parts) - 1)
        match = None
        if os.path.isdir(cur):
            try:
                for name in os.listdir(cur):
                    if name.lower() == part.lower():
                        match = name
                        break
            except OSError:
                pass
        if match is None:
            if not last and create_dirs:
                os.makedirs(os.path.join(cur, part), exist_ok=True)
                cur = os.path.join(cur, part)
                continue
            # 존재하지 않는 꼬리 부분은 주어진 표기 그대로
            return os.path.join(cur, *parts[i:]), False
        cur = os.path.join(cur, match)
    return cur, os.path.exists(cur)


def read_tsv(path):
    """UTF-8(BOM 허용) TSV → [(fields...)]; '#' 주석과 빈 줄 제외."""
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            rows.append(line.split("\t"))
    return rows


def is_ksx1001(kb):
    """EUC-KR(KS X 1001) 범위(0xA1~0xFE 쌍)만 허용. 0x80~0x8F는 게임 아이콘 코드라 금지."""
    i, n = 0, len(kb)
    while i < n:
        c = kb[i]
        if c < 0x80:
            i += 1
            continue
        if i + 1 >= n or not (0xA1 <= c <= 0xFE) or not (0xA1 <= kb[i + 1] <= 0xFE):
            return False
        i += 2
    return True


def game_running():
    try:
        if IS_WIN:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % GAME_EXE, "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout
            return GAME_EXE.lower() in out.lower()
        out = subprocess.run(["pgrep", "-fi", GAME_EXE], capture_output=True, text=True, timeout=10).stdout
        return bool(out.strip())
    except Exception:
        return False


# ----------------------------------------------------------------------------
# 게임 탐지
# ----------------------------------------------------------------------------
def _vdf_library_paths(vdf_path):
    paths = []
    try:
        with open(vdf_path, "r", encoding="utf-8", errors="replace") as f:
            for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                paths.append(m.group(1).replace("\\\\", "\\"))
    except OSError:
        pass
    return paths


def steam_roots():
    roots = []
    if IS_WIN:
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for name in ("SteamPath", "InstallPath"):
                            try:
                                v, _ = winreg.QueryValueEx(k, name)
                                roots.append(v)
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    else:
        home = os.path.expanduser("~")
        roots += [os.path.join(home, ".steam", "steam"),
                  os.path.join(home, ".steam", "root"),
                  os.path.join(home, ".local", "share", "Steam"),
                  os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),  # Flatpak
                  os.path.join(home, "snap", "steam", "common", ".local", "share", "Steam")]
        # Steam Deck SD 카드
        for mp in glob.glob("/run/media/*") + glob.glob("/run/media/*/*") + glob.glob("/media/*/*"):
            if os.path.isdir(os.path.join(mp, "steamapps")):
                roots.append(mp)
    out, seen = [], set()
    for r in roots:
        r = os.path.normpath(os.path.expanduser(r))
        if r.lower() not in seen and os.path.isdir(r):
            seen.add(r.lower())
            out.append(r)
    return out


def steam_libraries():
    libs = []
    for root in steam_roots():
        libs.append(root)
        libs += _vdf_library_paths(os.path.join(root, "steamapps", "libraryfolders.vdf"))
        libs += _vdf_library_paths(os.path.join(root, "config", "libraryfolders.vdf"))
    out, seen = [], set()
    for l in libs:
        l = os.path.normpath(l)
        if l.lower() not in seen and os.path.isdir(l):
            seen.add(l.lower())
            out.append(l)
    return out


def detect_game_dirs():
    found = []
    for lib in steam_libraries():
        cand = os.path.join(lib, "steamapps", "common", "Capitalism 2")
        if os.path.isfile(os.path.join(cand, GAME_EXE)):
            found.append(cand)
    # 흔한 비-Steam 경로
    for cand in (r"C:\Program Files (x86)\Capitalism 2", r"C:\Games\Capitalism 2"):
        if IS_WIN and os.path.isfile(os.path.join(cand, GAME_EXE)):
            found.append(cand)
    out, seen = [], set()
    for f in found:
        if f.lower() not in seen:
            seen.add(f.lower())
            out.append(f)
    return out


def user_data_dirs(game_dir):
    """CONFIG.DAT/SAVE 위치 후보(정보 표시용). 근거: FUN_004114b0 → <Documents>\\My Games\\Capitalism 2\\"""
    cands = []
    if IS_WIN:
        home = os.path.expanduser("~")
        cands.append(os.path.join(home, "Documents", "My Games", "Capitalism 2"))
        cands.append(os.path.join(home, "OneDrive", "Documents", "My Games", "Capitalism 2"))
    else:
        # Proton 프리픽스: <library>/steamapps/compatdata/638200/pfx/drive_c/users/steamuser/(My )Documents/My Games/Capitalism 2
        libs = steam_libraries()
        up = os.path.normpath(os.path.join(game_dir, "..", "..", ".."))
        if up not in libs:
            libs.insert(0, up)
        for lib in libs:
            pfx = os.path.join(lib, "steamapps", "compatdata", APP_ID, "pfx", "drive_c", "users", "steamuser")
            for docs in ("Documents", "My Documents"):
                cands.append(os.path.join(pfx, docs, "My Games", "Capitalism 2"))
    return [c for c in cands if os.path.isdir(c)]


# ----------------------------------------------------------------------------
# 게임 객체
# ----------------------------------------------------------------------------
class Game:
    def __init__(self, game_dir):
        self.dir = os.path.realpath(os.path.abspath(game_dir))   # 레지스트리의 소문자 경로를 실제 표기로 정규화
        self.exe = os.path.join(self.dir, GAME_EXE)
        if not os.path.isfile(self.exe):
            raise ModError("%s 가 없습니다: %s" % (GAME_EXE, self.dir))
        missing = [d for d in REQUIRED_DIRS if not resolve_case(self.dir, d)[1]]
        if missing:
            raise ModError("게임 폴더 구조가 아닙니다(없는 폴더: %s)" % ", ".join(missing))
        self.exe_sha = sha256_file(self.exe)
        self.state_dir = os.path.join(self.dir, STATE_DIRNAME)
        self.backup_dir = os.path.join(self.state_dir, "backup")
        self.manifest_path = os.path.join(self.state_dir, "manifest.json")
        self.vanilla_path = os.path.join(self.state_dir, "vanilla.json")

    @property
    def build_name(self):
        return KNOWN_EXE_SHA256.get(self.exe_sha, "알 수 없는 빌드")

    def path(self, rel, create_dirs=False):
        return resolve_case(self.dir, rel, create_dirs)

    def read(self, rel):
        p, ok = self.path(rel)
        if not ok:
            raise ModError("게임 파일 없음: %s" % rel)
        with open(p, "rb") as f:
            return f.read()

    # --- 상태 ---
    def load_manifest(self):
        if os.path.isfile(self.manifest_path):
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def save_manifest(self, m):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)

    def load_vanilla(self):
        if os.path.isfile(self.vanilla_path):
            with open(self.vanilla_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"exe_sha256": self.exe_sha, "files": {}}

    def save_vanilla(self, v):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self.vanilla_path, "w", encoding="utf-8") as f:
            json.dump(v, f, ensure_ascii=False, indent=2)

    def backup_path(self, rel):
        return os.path.join(self.backup_dir, *norm_rel(rel).split("/"))

    def original_bytes(self, rel):
        """원본(백업이 있으면 백업, 없으면 현재 게임 파일) 바이트. 없으면 None."""
        bp = self.backup_path(rel)
        if os.path.isfile(bp):
            with open(bp, "rb") as f:
                return f.read()
        p, ok = self.path(rel)
        if ok and os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
        return None


# ----------------------------------------------------------------------------
# PE 섹션 매핑 (exe 하드코딩 문자열 길이 검사용)
# ----------------------------------------------------------------------------
class PEMap:
    def __init__(self, data):
        self.data = data
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ModError("PE 시그니처 없음")
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        magic = struct.unpack_from("<H", data, opt)[0]
        self.image_base = struct.unpack_from("<I", data, opt + 28)[0] if magic == 0x10B else struct.unpack_from("<Q", data, opt + 24)[0]
        self.sections = []
        secoff = opt + opt_size
        for i in range(nsec):
            s = secoff + i * 40
            vsz, va, rawsz, rawoff = struct.unpack_from("<IIII", data, s + 8)
            self.sections.append((va, max(vsz, rawsz), rawoff))

    def va_to_off(self, va):
        rva = va - self.image_base
        for va0, sz, raw in self.sections:
            if va0 <= rva < va0 + sz:
                return rva - va0 + raw
        raise ModError("VA 0x%x 가 어느 섹션에도 없음" % va)

    def cstr_len(self, va):
        o = self.va_to_off(va)
        e = o
        while e < len(self.data) and self.data[e] != 0:
            e += 1
        return e - o


# ----------------------------------------------------------------------------
# ResourceIdx (*.RES/*.SET) — Resx.cpp 형식
#   s16 rec_count; struct { char name[9]; s32 offset; } idx[rec_count+1]; data...
#   마지막 항목(name 빈 문자열)의 offset = 파일 크기(데이터 끝)
# ----------------------------------------------------------------------------
class ResIdx:
    ENTRY = 13

    def __init__(self, data):
        if len(data) < 2:
            raise ModError("ResourceIdx: 파일이 너무 작음")
        self.count = struct.unpack_from("<h", data, 0)[0]
        need = 2 + (self.count + 1) * self.ENTRY
        if self.count < 0 or need > len(data):
            raise ModError("ResourceIdx: 인덱스 범위 오류(count=%d)" % self.count)
        self.records = []   # [name, bytes]
        offs = []
        names = []
        for i in range(self.count + 1):
            o = 2 + i * self.ENTRY
            names.append(data[o:o + 9].split(b"\0", 1)[0].decode("latin-1"))
            offs.append(struct.unpack_from("<i", data, o + 9)[0])
        for i in range(self.count):
            a, b = offs[i], offs[i + 1]
            if not (need <= a <= b <= len(data)):
                raise ModError("ResourceIdx: 레코드 %d(%s) 오프셋 오류" % (i, names[i]))
            self.records.append([names[i], data[a:b]])

    @classmethod
    def is_residx(cls, data):
        try:
            cls(data)
            return True
        except ModError:
            return False

    def find(self, name):
        for i, (n, _) in enumerate(self.records):
            if n.upper() == name.upper():
                return i
        return -1

    def to_bytes(self):
        n = len(self.records)
        out = io.BytesIO()
        out.write(struct.pack("<h", n))
        off = 2 + (n + 1) * self.ENTRY
        for name, blob in self.records:
            nb = name.encode("latin-1")[:8].ljust(9, b"\0")
            out.write(nb + struct.pack("<i", off))
            off += len(blob)
        out.write(b"\0" * 9 + struct.pack("<i", off))
        for _, blob in self.records:
            out.write(blob)
        return out.getvalue()


# ----------------------------------------------------------------------------
# 텍스트 리소스(Txtres.cpp) 줄 번호 치환
# ----------------------------------------------------------------------------
_LINE_RE = re.compile(r"^(\[[^\]]*\])?(.*?)(\|?)(\x1a?)(\r?\n?)$", re.S)


def patch_text_res(orig, rel, line_map, enc, strict_ksx):
    """
    orig: 원본 바이트. line_map: {줄번호(1-base): 한국어}. .des 는 {1: 전체 본문}.
    Txtres 로더는 줄 번호 인덱스이므로 줄 수/[TAG]/끝 '|'/0x1A/개행을 그대로 유지한다.
    """
    errors = []
    if rel.lower().endswith(".des"):
        ko = line_map.get(1)
        if ko is None:
            return orig, errors
        kb = ko.encode(enc, errors="strict")
        if strict_ksx and not is_ksx1001(kb):
            errors.append("KS X 1001 범위 밖: %s" % rel)
            return orig, errors
        out = kb + (b"\x1a" if orig.endswith(b"\x1a") else b"")
        return out, errors
    text = orig.decode("latin-1")
    segs = [s for s in re.split(r"(?<=\n)", text) if s != ""]
    out = io.BytesIO()
    for n, seg in enumerate(segs, 1):
        if n not in line_map:
            out.write(seg.encode("latin-1"))
            continue
        m = _LINE_RE.match(seg)
        tag, body, pipe, eof, nl = m.groups()
        try:
            kb = line_map[n].encode(enc, errors="strict")
        except UnicodeEncodeError as ue:
            # 대상 코드페이지에 없는 문자(예: U+2014 '—')는 '?'로 대체하고 알린다(줄 구조는 유지)
            errors.append("%s 행 %d: '%s' 는 %s 에 없어 '?'로 대체" % (rel, n, line_map[n][ue.start:ue.end], enc))
            kb = line_map[n].encode(enc, errors="replace")
        if strict_ksx and not is_ksx1001(kb):
            errors.append("KS X 1001 범위 밖: %s 행 %d" % (rel, n))
            kb = body.encode("latin-1")
        out.write(tag.encode("latin-1") if tag else b"")
        out.write(kb)
        out.write((pipe + eof + nl).encode("latin-1"))
    res = out.getvalue()
    if orig.count(b"\n") != res.count(b"\n"):
        errors.append("줄 수 불일치 %s: 원본 %d, 결과 %d" % (rel, orig.count(b"\n"), res.count(b"\n")))
    return res, errors


def build_translat(pairs, enc, strict_ksx):
    """
    [(영어, 한국어)] → TRANSLAT.RES 바이트. Transl.cpp 파서 형식: 영어|한국어~\\r\\n ... 0x1A
    '|'/'~' 는 구분자라 사용 불가. 영어 키는 Font::put 에 넘어오는 문자열과 바이트 단위로 같아야 함.
    """
    out = io.BytesIO()
    n = skipped = 0
    for en, ko in pairs:
        if any(c in en for c in "|~") or any(c in ko for c in "|~"):
            warn("TRANSLAT 구분자('|','~') 포함 항목 건너뜀: %s" % en)
            skipped += 1
            continue
        try:
            kb = ko.encode(enc)
            eb = en.encode(enc)
        except UnicodeEncodeError:
            warn("TRANSLAT 인코딩 불가 건너뜀: %s" % en)
            skipped += 1
            continue
        if strict_ksx and not is_ksx1001(kb):
            warn("TRANSLAT KS X 1001 범위 밖 건너뜀: %s → %s" % (en, ko))
            skipped += 1
            continue
        out.write(eb + b"|" + kb + b"~\r\n")
        n += 1
    out.write(b"\x1a")
    return out.getvalue(), n, skipped


def build_exe_strings(rows, pe, enc, strict_ksx):
    """[(주소문자열, 영어, 한국어)] → cap2kr_exe.txt ("0x주소|한국어\\r\\n"). 원문 길이 이하만 허용."""
    out = io.BytesIO()
    n = bad = 0
    for addr, en, ko in rows:
        va = int(addr, 16)
        kb = ko.encode(enc)
        ol = pe.cstr_len(va)
        if len(kb) > ol:
            warn("exe 문자열 길이 초과 %s: %dB > %dB '%s' → '%s'" % (addr, len(kb), ol, en, ko))
            bad += 1
            continue
        if strict_ksx and not is_ksx1001(kb):
            warn("exe 문자열 KS X 1001 범위 밖: %s %s" % (addr, ko))
            bad += 1
            continue
        out.write(addr.encode("ascii") + b"|" + kb + b"\r\n")
        n += 1
    return out.getvalue(), n, bad


# ----------------------------------------------------------------------------
# 모드
# ----------------------------------------------------------------------------
class Mod:
    def __init__(self, mod_dir):
        self.dir = os.path.abspath(mod_dir)
        jp = os.path.join(self.dir, "mod.json")
        if not os.path.isfile(jp):
            raise ModError("mod.json 없음: %s" % self.dir)
        with open(jp, "r", encoding="utf-8-sig") as f:
            self.meta = json.load(f)
        self.id = self.meta.get("id") or os.path.basename(self.dir)
        if not re.match(r"^[A-Za-z0-9_.-]+$", self.id):
            raise ModError("모드 id 는 영숫자/_/-/. 만 허용: %s" % self.id)
        self.name = self.meta.get("name", self.id)
        self.version = str(self.meta.get("version", "0"))
        self.author = self.meta.get("author", "")
        self.description = self.meta.get("description", "")
        self.priority = int(self.meta.get("priority", 100))
        self.requires = list(self.meta.get("requires", []))
        self.conflicts = list(self.meta.get("conflicts", []))
        self.requires_exe = [s.lower() for s in self.meta.get("requires_exe_sha256", [])]
        self.encoding = self.meta.get("encoding", "cp949")
        self.ksx1001_only = bool(self.meta.get("ksx1001_only", self.encoding.lower() in ("cp949", "euc-kr", "euc_kr", "ms949")))
        self.files_dir = self.meta.get("files", "files")
        self.text_patches = list(self.meta.get("text_patches", []))
        self.translat = list(self.meta.get("translat", []))
        self.exe_strings = list(self.meta.get("exe_strings", []))
        self.res_records = list(self.meta.get("res_records", []))
        self.proxy_dll = self.meta.get("proxy_dll")   # {"file":"SDL2.dll","original_as":"SDL2_org.dll"} 또는 "SDL2.dll"
        if isinstance(self.proxy_dll, str):
            base, ext = os.path.splitext(self.proxy_dll)
            self.proxy_dll = {"file": self.proxy_dll, "original_as": base + "_org" + ext}
        self.default_enabled = bool(self.meta.get("default_enabled", True))

    def _globs(self, patterns):
        out = []
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(self.dir, pat)))
            if not hits:
                warn("[%s] 패턴에 맞는 파일 없음: %s" % (self.id, pat))
            out += hits
        return out

    def overlay_files(self):
        """[(상대경로, 절대경로)] — files/ 아래 모든 파일(게임 루트 기준 상대 경로)."""
        base = os.path.join(self.dir, self.files_dir)
        out = []
        if os.path.isdir(base):
            for root, _, files in os.walk(base):
                for fn in files:
                    ap = os.path.join(root, fn)
                    out.append((norm_rel(os.path.relpath(ap, base)), ap))
        return sorted(out)

    def text_patch_map(self):
        """{상대경로: {줄번호: 한국어}} — file<TAB>line<TAB>ko"""
        m = {}
        for p in self._globs(self.text_patches):
            for row in read_tsv(p):
                if len(row) < 3 or row[2] == "":
                    continue
                rel = norm_rel(row[0])
                try:
                    ln = int(row[1])
                except ValueError:
                    warn("[%s] 줄 번호가 아님: %s" % (self.id, row[:2]))
                    continue
                m.setdefault(rel, {})[ln] = row[2]
        return m

    def translat_pairs(self):
        """[(영어, 한국어)] — 한 모드 안에서는 먼저 나온 키가 우선."""
        pairs, seen = [], set()
        for p in self._globs(self.translat):
            for row in read_tsv(p):
                if len(row) < 2 or row[1] == "":
                    continue
                if row[0] in seen:
                    continue
                seen.add(row[0])
                pairs.append((row[0], row[1]))
        return pairs

    def exe_string_rows(self):
        rows = []
        for p in self._globs(self.exe_strings):
            for row in read_tsv(p):
                if len(row) < 3 or row[2] == "":
                    continue
                rows.append((row[0], row[1], row[2]))
        return rows

    def summary(self):
        kinds = []
        if self.overlay_files():
            kinds.append("files")
        if self.text_patches:
            kinds.append("text")
        if self.translat:
            kinds.append("translat")
        if self.exe_strings:
            kinds.append("exe-strings")
        if self.res_records:
            kinds.append("res-records")
        if self.proxy_dll:
            kinds.append("proxy-dll")
        return ",".join(kinds) or "-"


def load_mods(mods_dir=MODS_DIR):
    mods = {}
    if not os.path.isdir(mods_dir):
        return mods
    for d in sorted(os.listdir(mods_dir)):
        md = os.path.join(mods_dir, d)
        if os.path.isdir(md) and os.path.isfile(os.path.join(md, "mod.json")):
            try:
                m = Mod(md)
            except Exception as e:
                warn("모드 로드 실패 %s: %s" % (d, e))
                continue
            if m.id in mods:
                warn("중복 모드 id %s (%s 무시)" % (m.id, d))
                continue
            mods[m.id] = m
    return mods


ENABLED_PATH = os.path.join(MODS_DIR, "enabled.json")


def load_enabled(mods):
    if os.path.isfile(ENABLED_PATH):
        with open(ENABLED_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        en = data.get("enabled", {})
        if isinstance(en, list):
            en = {k: True for k in en}
    else:
        en = {}
    return {mid: bool(en.get(mid, m.default_enabled)) for mid, m in mods.items()}


def save_enabled(enabled):
    os.makedirs(MODS_DIR, exist_ok=True)
    with open(ENABLED_PATH, "w", encoding="utf-8") as f:
        json.dump({"enabled": enabled}, f, ensure_ascii=False, indent=2)


def ordered_active_mods(mods, enabled):
    active = [m for mid, m in mods.items() if enabled.get(mid)]
    active.sort(key=lambda m: (m.priority, m.id))
    ids = {m.id for m in active}
    for m in active:
        for r in m.requires:
            if r not in ids:
                raise ModError("모드 '%s' 는 '%s' 를 필요로 하지만 활성화되어 있지 않습니다." % (m.id, r))
        for c in m.conflicts:
            if c in ids:
                raise ModError("모드 '%s' 와 '%s' 는 함께 쓸 수 없습니다." % (m.id, c))
    return active


# ----------------------------------------------------------------------------
# 설정
# ----------------------------------------------------------------------------
def load_config():
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_game(args_game=None, interactive=False):
    cfg = load_config()
    cand = args_game or cfg.get("game_dir")
    if cand and os.path.isfile(os.path.join(cand, GAME_EXE)):
        g = Game(cand)
    else:
        found = detect_game_dirs()
        if not found:
            raise ModError("게임을 찾지 못했습니다. --game \"<Capitalism 2 폴더>\" 로 지정하세요.")
        if len(found) > 1:
            log("게임 폴더 후보가 여러 개입니다. 첫 번째를 사용합니다:")
            for f in found:
                log("  " + f)
        g = Game(found[0])
    if cfg.get("game_dir") != g.dir:
        cfg["game_dir"] = g.dir
        save_config(cfg)
    return g


# ----------------------------------------------------------------------------
# 적용 / 복원 / 검증
# ----------------------------------------------------------------------------
def plan_apply(game, active):
    """
    활성 모드 → {상대경로: {"data": bytes, "mods": [id...]}} 계획.
    1) files/ 오버레이(우선순위 낮은 것부터 덮어씀) 2) res_records 3) text_patches 4) translat 5) exe_strings
    생성물(3~5)은 모드 간 병합 결과이므로 오버레이보다 우선한다(충돌 시 경고).
    """
    plan = {}
    proxies = []

    def put(rel, data, mod_id, kind):
        key = norm_rel(rel)
        if key in plan and plan[key]["mods"][-1] != mod_id:
            log("  충돌: %s ← %s 가 %s 를 덮어씀 (%s)" % (key, mod_id, plan[key]["mods"][-1], kind))
        e = plan.setdefault(key, {"data": None, "mods": [], "kinds": []})
        e["data"] = data
        e["mods"].append(mod_id)
        e["kinds"].append(kind)

    # 1) 오버레이
    for m in active:
        for rel, ap in m.overlay_files():
            with open(ap, "rb") as f:
                put(rel, f.read(), m.id, "file")
        if m.proxy_dll:
            proxies.append((m.id, m.proxy_dll))

    # 2) RES 레코드 교체
    for m in active:
        for spec in m.res_records:
            rel = norm_rel(spec["file"])
            base = plan[rel]["data"] if rel in plan else game.original_bytes(rel)
            if base is None:
                raise ModError("[%s] res_records 대상 없음: %s" % (m.id, rel))
            ri = ResIdx(base)
            src = os.path.join(m.dir, spec["from"])
            with open(src, "rb") as f:
                blob = f.read()
            idx = ri.find(spec["record"])
            if idx < 0:
                if spec.get("add", False):
                    ri.records.append([spec["record"], blob])
                else:
                    raise ModError("[%s] %s 에 레코드 '%s' 없음" % (m.id, rel, spec["record"]))
            else:
                ri.records[idx][1] = blob
            put(rel, ri.to_bytes(), m.id, "res-record")

    # 3) 텍스트 줄 치환 (모드 간 병합: 우선순위 높은 모드가 같은 줄을 덮어씀)
    merged = {}
    meta = {}
    for m in active:
        for rel, lm in m.text_patch_map().items():
            merged.setdefault(rel, {}).update(lm)
            meta[rel] = (m.encoding, m.ksx1001_only, m.id)
    for rel, lm in sorted(merged.items()):
        base = plan[rel]["data"] if rel in plan else game.original_bytes(rel)
        if base is None:
            warn("텍스트 치환 대상 원본 없음: %s" % rel)
            continue
        enc, strict, mid = meta[rel]
        data, errs = patch_text_res(base, rel, lm, enc, strict)
        for e in errs:
            warn(e)
        put(rel, data, mid, "text(%d줄)" % len(lm))

    # 4) TRANSLAT.RES
    pairs, seen = [], {}
    for m in active:                      # 낮은 우선순위부터 넣고, 높은 모드가 같은 키를 덮어씀
        for en, ko in m.translat_pairs():
            if en in seen:
                pairs[seen[en]] = (en, ko)
            else:
                seen[en] = len(pairs)
                pairs.append((en, ko))
    if pairs:
        last = [m for m in active if m.translat][-1]
        data, n, skipped = build_translat(pairs, last.encoding, last.ksx1001_only)
        put("Resource/TRANSLAT.RES", data, last.id, "translat(%d항목)" % n)

    # 5) exe 하드코딩 문자열 (프록시 DLL이 읽는 cap2kr_exe.txt)
    rows, seen = [], {}
    for m in active:
        if m.exe_strings and m.requires_exe and game.exe_sha.lower() not in m.requires_exe:
            raise ModError("모드 '%s' 는 특정 Cap2.exe 빌드 전용입니다(현재: %s…). exe 문자열 패치를 적용할 수 없습니다." % (m.id, game.exe_sha[:12]))
        for addr, en, ko in m.exe_string_rows():
            key = addr.lower()
            if key in seen:
                rows[seen[key]] = (addr, en, ko)
            else:
                seen[key] = len(rows)
                rows.append((addr, en, ko))
    if rows:
        last = [m for m in active if m.exe_strings][-1]
        with open(game.exe, "rb") as f:
            pe = PEMap(f.read())
        data, n, bad = build_exe_strings(rows, pe, last.encoding, last.ksx1001_only)
        put(last.meta.get("exe_strings_out", "cap2kr_exe.txt"), data, last.id, "exe-strings(%d항목)" % n)

    return plan, proxies


def do_apply(game, mods, enabled, dry_run=False):
    if game_running():
        raise ModError("%s 가 실행 중입니다. 게임을 종료한 뒤 다시 실행하세요." % GAME_EXE)
    active = ordered_active_mods(mods, enabled)
    for m in active:
        if m.requires_exe and game.exe_sha.lower() not in m.requires_exe and not m.exe_strings:
            warn("모드 '%s' 는 다른 Cap2.exe 빌드용으로 만들어졌습니다(현재 %s). 동작을 보장할 수 없습니다." % (m.id, game.build_name))
    log("게임: %s  [%s]" % (game.dir, game.build_name))
    log("활성 모드(%d): %s" % (len(active), ", ".join("%s@%s" % (m.id, m.version) for m in active) or "-"))

    # 이미 적용된 상태면 먼저 원본 복원(멱등)
    if game.load_manifest():
        log("기존 적용 상태 발견 → 원본 복원 후 다시 적용합니다.")
        if not dry_run:
            do_restore(game, quiet=True)

    plan, proxies = plan_apply(game, active)
    if not plan and not proxies:
        log("적용할 내용이 없습니다.")
        return

    vanilla = game.load_vanilla()
    manifest = {"version": VERSION, "applied_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exe_sha256": game.exe_sha, "mods": [{"id": m.id, "version": m.version} for m in active],
                "files": [], "created": []}

    # 프록시 DLL: 원본 X.dll → X_org.dll 보존 (DLL 포워딩 규약)
    for mid, pd in proxies:
        rel = norm_rel(pd["file"])
        org_rel = norm_rel(pd["original_as"])
        if rel not in plan:
            warn("[%s] proxy_dll '%s' 가 files/ 에 없습니다." % (mid, rel))
            continue
        cur, ok = game.path(rel)
        org, org_ok = game.path(org_rel)
        if not ok:
            raise ModError("[%s] 원본 DLL 없음: %s" % (mid, rel))
        if org_ok:
            warn("%s 가 이미 존재합니다(이전 프록시 설치 흔적). 그대로 원본으로 간주합니다." % org_rel)
        else:
            log("  원본 보존: %s → %s" % (rel, org_rel))
            if not dry_run:
                shutil.copy2(cur, org)
                manifest["created"].append(org_rel)

    # 파일 쓰기
    for rel in sorted(plan):
        data = plan[rel]["data"]
        target, exists = game.path(rel, create_dirs=not dry_run)
        entry = {"rel": rel, "mods": plan[rel]["mods"], "kinds": plan[rel]["kinds"],
                 "sha256": sha256_bytes(data), "existed": exists}
        if exists:
            bp = game.backup_path(rel)
            if not os.path.isfile(bp):
                if not dry_run:
                    os.makedirs(os.path.dirname(bp), exist_ok=True)
                    shutil.copy2(target, bp)
                h = sha256_file(target)
                vanilla["files"][rel] = h
            entry["orig_sha256"] = vanilla["files"].get(rel)
        log("  %-36s %-24s ← %s" % (rel, "/".join(plan[rel]["kinds"]), ",".join(plan[rel]["mods"])))
        if not dry_run:
            with open(target, "wb") as f:
                f.write(data)
        manifest["files"].append(entry)

    if dry_run:
        log("(dry-run: 변경하지 않음)")
        return
    game.save_vanilla(vanilla)
    game.save_manifest(manifest)
    log("적용 완료: 파일 %d개, 생성 %d개. 상태: %s" % (len(manifest["files"]), len(manifest["created"]), game.manifest_path))


def do_restore(game, quiet=False):
    if game_running():
        raise ModError("%s 가 실행 중입니다. 게임을 종료한 뒤 다시 실행하세요." % GAME_EXE)
    m = game.load_manifest()
    if not m:
        log("적용된 모드가 없습니다(manifest 없음).")
        return
    n_restored = n_deleted = 0
    for e in m["files"]:
        rel = e["rel"]
        target, exists = game.path(rel)
        if e.get("existed"):
            bp = game.backup_path(rel)
            if os.path.isfile(bp):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(bp, target)
                os.remove(bp)
                n_restored += 1
            else:
                warn("백업 없음(복원 불가): %s" % rel)
        elif exists:
            os.remove(target)
            n_deleted += 1
    for rel in m.get("created", []):
        p, ok = game.path(rel)
        if ok:
            os.remove(p)
            n_deleted += 1
    # 빈 백업 디렉터리 정리
    for root, dirs, files in os.walk(game.backup_dir, topdown=False):
        if not dirs and not files and root != game.backup_dir:
            try:
                os.rmdir(root)
            except OSError:
                pass
    os.remove(game.manifest_path)
    if not quiet:
        log("복원 완료: 원본 복원 %d개, 생성 파일 삭제 %d개" % (n_restored, n_deleted))


def do_verify(game):
    m = game.load_manifest()
    if not m:
        log("적용된 모드가 없습니다.")
        return True
    ok = True
    if m.get("exe_sha256") != game.exe_sha:
        warn("Cap2.exe 가 적용 당시와 다릅니다(게임 업데이트?).")
        ok = False
    for e in m["files"]:
        p, exists = game.path(e["rel"])
        if not exists:
            log("  없음     %s" % e["rel"])
            ok = False
            continue
        h = sha256_file(p)
        if h != e["sha256"]:
            state = "원본으로 되돌아감(Steam 무결성 검사?)" if h == e.get("orig_sha256") else "외부 변경"
            log("  변경됨   %s  (%s)" % (e["rel"], state))
            ok = False
    log("검증 결과: %s" % ("정상(적용 상태 유지)" if ok else "불일치 있음 → apply 를 다시 실행하세요"))
    return ok


def do_status(game, mods, enabled):
    log("게임 폴더 : %s" % game.dir)
    log("Cap2.exe  : %s  [%s]" % (game.exe_sha[:16] + "…", game.build_name))
    ud = user_data_dirs(game.dir)
    log("사용자 데이터(CONFIG.DAT/SAVE): %s" % (ud[0] if ud else "(미발견) Documents\\My Games\\Capitalism 2"))
    m = game.load_manifest()
    if m:
        log("적용 상태 : %s 에 모드 %d개 적용, 파일 %d개 변경" % (m["applied_at"], len(m["mods"]), len(m["files"])))
        for mm in m["mods"]:
            log("   - %s@%s" % (mm["id"], mm["version"]))
    else:
        log("적용 상태 : 원본(적용된 모드 없음)")
    org, ok = game.path("SDL2_org.dll")
    if ok and not m:
        warn("SDL2_org.dll 이 있습니다. 매니저 밖에서 설치된 프록시 DLL 흔적일 수 있습니다.")
    log("모드 폴더 : %s (%d개, 활성 %d개)" % (MODS_DIR, len(mods), sum(1 for v in enabled.values() if v)))


def do_list(mods, enabled):
    if not mods:
        log("mods/ 에 모드가 없습니다: %s" % MODS_DIR)
        return
    log("%-3s %-20s %-10s %-5s %-30s %s" % ("", "id", "version", "prio", "종류", "이름"))
    for m in sorted(mods.values(), key=lambda m: (m.priority, m.id)):
        log("%-3s %-20s %-10s %-5d %-30s %s" % ("[x]" if enabled.get(m.id) else "[ ]", m.id, m.version, m.priority, m.summary(), m.name))


# ----------------------------------------------------------------------------
# 모드 제작 보조: 텍스트 덤프 / RES 인덱스 조회·추출
# ----------------------------------------------------------------------------
def do_dump_text(game, rel, out_path):
    data = game.original_bytes(rel)
    if data is None:
        raise ModError("파일 없음: %s" % rel)
    text = data.decode("latin-1")
    segs = [s for s in re.split(r"(?<=\n)", text) if s != ""]
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s 원문 덤프: file\\tline\\t원문  → 3열을 번역문으로 바꿔 text_patches 에 넣으세요\n" % rel)
        for n, seg in enumerate(segs, 1):
            m = _LINE_RE.match(seg)
            body = m.group(2)
            if rel.lower().endswith(".des"):
                body = text.rstrip("\x1a")
                f.write("%s\t1\t%s\n" % (rel, body.replace("\r\n", "\\n").replace("\n", "\\n")))
                break
            f.write("%s\t%d\t%s\n" % (rel, n, body))
    log("덤프 완료: %s (%d줄)" % (out_path, len(segs)))


def do_res(game, rel, action, record=None, out=None):
    data = game.original_bytes(rel)
    if data is None:
        raise ModError("파일 없음: %s" % rel)
    ri = ResIdx(data)
    if action == "ls":
        log("%s: 레코드 %d개" % (rel, ri.count))
        off = 2 + (ri.count + 1) * ResIdx.ENTRY
        for i, (name, blob) in enumerate(ri.records):
            kind = ""
            if blob[:1] == b"\x03" and len(blob) > 32:
                kind = "DBF(dBase III)"
            elif len(blob) >= 4 and 0 < struct.unpack_from("<H", blob, 0)[0] < 2048 and 0 < struct.unpack_from("<H", blob, 2)[0] < 2048:
                kind = "bitmap? %dx%d" % struct.unpack_from("<HH", blob, 0)
            log("  [%3d] %-9s off=%-8d size=%-8d %s" % (i, name, off, len(blob), kind))
            off += len(blob)
    elif action == "extract":
        idx = ri.find(record) if record else -1
        if record and idx < 0:
            raise ModError("레코드 없음: %s" % record)
        targets = [idx] if record else range(len(ri.records))
        os.makedirs(out, exist_ok=True)
        for i in targets:
            name, blob = ri.records[i]
            p = os.path.join(out, "%03d_%s.bin" % (i, name or "unnamed"))
            with open(p, "wb") as f:
                f.write(blob)
        log("추출 완료 → %s" % out)


# ----------------------------------------------------------------------------
# GUI (tkinter, 선택)
# ----------------------------------------------------------------------------
def run_gui(args):
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox, scrolledtext
    except ImportError:
        raise ModError("tkinter 가 없어 GUI를 열 수 없습니다. CLI 명령(list/apply/restore/status)을 사용하세요.")

    root = tk.Tk()
    root.title("Capitalism 2 모드 매니저 (cap2mod %s)" % VERSION)
    root.geometry("860x600")

    state = {"game": None, "mods": {}, "enabled": {}}

    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="게임 폴더:").pack(side="left")
    game_var = tk.StringVar()
    ent = ttk.Entry(top, textvariable=game_var)
    ent.pack(side="left", fill="x", expand=True, padx=4)

    mid = ttk.Frame(root, padding=(8, 0))
    mid.pack(fill="both", expand=True)
    cols = ("on", "id", "version", "prio", "kinds", "name")
    tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse", height=10)
    for c, w, t in (("on", 40, "활성"), ("id", 160, "id"), ("version", 70, "버전"), ("prio", 50, "순서"), ("kinds", 200, "종류"), ("name", 300, "이름")):
        tree.heading(c, text=t)
        tree.column(c, width=w, anchor="w")
    tree.pack(fill="both", expand=True)

    desc_var = tk.StringVar()
    ttk.Label(root, textvariable=desc_var, wraplength=820, padding=(8, 4)).pack(fill="x")

    logbox = scrolledtext.ScrolledText(root, height=12, font=("Consolas" if IS_WIN else "monospace", 9))
    logbox.pack(fill="both", expand=True, padx=8, pady=4)

    def gui_log(s):
        logbox.insert("end", s + "\n")
        logbox.see("end")
        root.update_idletasks()
    _LOG_SINK[0] = gui_log

    def refresh_mods():
        state["mods"] = load_mods()
        state["enabled"] = load_enabled(state["mods"])
        tree.delete(*tree.get_children())
        for m in sorted(state["mods"].values(), key=lambda m: (m.priority, m.id)):
            tree.insert("", "end", iid=m.id, values=("☑" if state["enabled"][m.id] else "☐", m.id, m.version, m.priority, m.summary(), m.name))

    def set_game(path):
        try:
            g = Game(path)
        except Exception as e:
            messagebox.showerror("게임 인식 실패", str(e))
            return
        state["game"] = g
        game_var.set(g.dir)
        cfg = load_config()
        cfg["game_dir"] = g.dir
        save_config(cfg)
        gui_log("게임 인식: %s [%s]" % (g.dir, g.build_name))
        m = g.load_manifest()
        gui_log("현재 상태: " + ("모드 %d개 적용됨" % len(m["mods"]) if m else "원본"))

    def on_detect():
        found = detect_game_dirs()
        if not found:
            messagebox.showwarning("자동 탐지", "Steam 라이브러리에서 Capitalism 2 를 찾지 못했습니다. [찾기]로 폴더를 지정하세요.")
            return
        set_game(found[0])

    def on_browse():
        d = filedialog.askdirectory(title="Capitalism 2 폴더(Cap2.exe 위치) 선택")
        if d:
            set_game(d)

    def need_game():
        if not state["game"]:
            messagebox.showwarning("게임 미지정", "먼저 게임 폴더를 인식시키세요.")
            return False
        return True

    def toggle(event=None):
        sel = tree.selection()
        if not sel:
            return
        mid_ = sel[0]
        state["enabled"][mid_] = not state["enabled"][mid_]
        save_enabled(state["enabled"])
        tree.set(mid_, "on", "☑" if state["enabled"][mid_] else "☐")

    def on_select(event=None):
        sel = tree.selection()
        if sel and sel[0] in state["mods"]:
            m = state["mods"][sel[0]]
            desc_var.set("%s %s — %s\n%s" % (m.name, m.version, m.author, m.description))

    def guarded(fn):
        def run():
            try:
                fn()
            except ModError as e:
                gui_log("오류: %s" % e)
                messagebox.showerror("오류", str(e))
            except Exception as e:
                gui_log("예외: %r" % e)
                messagebox.showerror("예외", repr(e))
        return run

    def on_apply():
        if not need_game():
            return
        do_apply(state["game"], state["mods"], state["enabled"])

    def on_restore():
        if not need_game():
            return
        do_restore(state["game"])

    def on_status():
        if not need_game():
            return
        do_status(state["game"], state["mods"], state["enabled"])
        do_verify(state["game"])

    btns = ttk.Frame(root, padding=8)
    btns.pack(fill="x")
    ttk.Button(top, text="자동 탐지", command=guarded(on_detect)).pack(side="left", padx=2)
    ttk.Button(top, text="찾기…", command=guarded(on_browse)).pack(side="left", padx=2)
    ttk.Button(btns, text="활성/비활성 전환", command=guarded(toggle)).pack(side="left", padx=2)
    ttk.Button(btns, text="모드 새로 읽기", command=guarded(refresh_mods)).pack(side="left", padx=2)
    ttk.Button(btns, text="모드 폴더 열기", command=guarded(lambda: _open_folder(MODS_DIR))).pack(side="left", padx=2)
    ttk.Button(btns, text="상태/검증", command=guarded(on_status)).pack(side="right", padx=2)
    ttk.Button(btns, text="원본 복원", command=guarded(on_restore)).pack(side="right", padx=2)
    ttk.Button(btns, text="적용", command=guarded(on_apply)).pack(side="right", padx=2)
    tree.bind("<Double-1>", lambda e: guarded(toggle)())
    tree.bind("<<TreeviewSelect>>", on_select)

    refresh_mods()
    cfg = load_config()
    start = args.game or cfg.get("game_dir")
    if start and os.path.isfile(os.path.join(start, GAME_EXE)):
        set_game(start)
    else:
        found = detect_game_dirs()
        if found:
            set_game(found[0])
        else:
            gui_log("게임을 자동으로 찾지 못했습니다. [찾기…]로 Cap2.exe 가 있는 폴더를 지정하세요.")
    root.mainloop()


def _open_folder(path):
    os.makedirs(path, exist_ok=True)
    if IS_WIN:
        os.startfile(path)  # noqa
    else:
        subprocess.Popen(["xdg-open", path])


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main(argv=None):
    _setup_console()
    ap = argparse.ArgumentParser(prog="cap2mod", description="Capitalism 2 모드 매니저 (Windows/Linux)")
    ap.add_argument("--game", help="Capitalism 2 폴더(Cap2.exe 위치). 생략 시 자동 탐지/저장된 경로")
    ap.add_argument("--mods", help="모드 폴더(기본: 매니저 폴더의 mods/)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("detect", help="Steam 라이브러리에서 게임 폴더 탐지")
    sub.add_parser("status", help="게임/적용 상태 표시")
    sub.add_parser("list", help="모드 목록")
    p = sub.add_parser("enable", help="모드 활성화"); p.add_argument("ids", nargs="+")
    p = sub.add_parser("disable", help="모드 비활성화"); p.add_argument("ids", nargs="+")
    p = sub.add_parser("apply", help="활성 모드를 게임에 적용(원본 백업)"); p.add_argument("--dry-run", action="store_true")
    sub.add_parser("restore", help="원본 복원")
    sub.add_parser("verify", help="적용 상태가 유지되는지 해시 검증")
    p = sub.add_parser("dump-text", help="텍스트 .res/.des 원문을 TSV로 덤프(번역 모드 제작용)")
    p.add_argument("rel"); p.add_argument("out")
    p = sub.add_parser("res", help="ResourceIdx(*.RES/*.SET) 레코드 조회/추출")
    p.add_argument("action", choices=["ls", "extract"]); p.add_argument("rel")
    p.add_argument("--record"); p.add_argument("--out", default="res_out")
    sub.add_parser("gui", help="GUI 실행(tkinter)")
    args = ap.parse_args(argv)

    global MODS_DIR, ENABLED_PATH
    if args.mods:
        MODS_DIR = os.path.abspath(args.mods)
        ENABLED_PATH = os.path.join(MODS_DIR, "enabled.json")

    try:
        if args.cmd is None or args.cmd == "gui":
            if args.cmd is None and not sys.stdin.isatty() and not IS_WIN:
                ap.print_help()
                return 0
            run_gui(args)
            return 0
        if args.cmd == "detect":
            found = detect_game_dirs()
            if not found:
                log("찾지 못함. Steam 라이브러리: %s" % (steam_libraries() or "-"))
                return 1
            for f in found:
                g = Game(f)
                log("%s  [%s]" % (g.dir, g.build_name))
            return 0
        mods = load_mods(MODS_DIR)
        enabled = load_enabled(mods)
        if args.cmd == "list":
            do_list(mods, enabled)
            return 0
        if args.cmd in ("enable", "disable"):
            for i in args.ids:
                if i not in mods:
                    raise ModError("모드 없음: %s" % i)
                enabled[i] = (args.cmd == "enable")
            save_enabled(enabled)
            do_list(mods, enabled)
            return 0
        game = get_game(args.game)
        if args.cmd == "status":
            do_status(game, mods, enabled)
        elif args.cmd == "apply":
            do_apply(game, mods, enabled, dry_run=args.dry_run)
        elif args.cmd == "restore":
            do_restore(game)
        elif args.cmd == "verify":
            return 0 if do_verify(game) else 2
        elif args.cmd == "dump-text":
            do_dump_text(game, norm_rel(args.rel), args.out)
        elif args.cmd == "res":
            do_res(game, norm_rel(args.rel), args.action, args.record, args.out)
        return 0
    except ModError as e:
        log("오류: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
