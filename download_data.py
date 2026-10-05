"""
Indux - download the public benchmark datasets in one command.

    python download_data.py                    # everything that is missing (~1.2 GB in total, mostly IMS)
    python download_data.py --only ai4i cwru   # skip the big NASA IMS archive
    python download_data.py --check            # just report what is there
    python download_data.py --only cwru --files 97 105   # specific CWRU file numbers

Sources (official, no account needed):
  AI4I 2020   UCI Machine Learning Repository                       ~0.5 MB
  CWRU        Case Western Reserve University Bearing Data Center   40 files, ~250 MB
  NASA IMS    NASA Prognostics Data Repository ("4. Bearings")      1.07 GB zip -> test 2 only (~520 MB)

Files land where the training scripts expect them (data/benchmark/{ai4i,cwru,ims}). Anything already
present and valid is skipped, so it is safe to re-run after an interrupted download.

The IMS archive is nested (zip -> .7z -> .rar). The script unpacks it with 7-Zip if installed, else with
`tar` (libarchive, built into Windows 10+ / macOS), else with the py7zr + rarfile Python packages. If none
of them can open it, it prints the exact manual steps.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "data" / "benchmark"

AI4I_URL = "https://archive.ics.uci.edu/static/public/601/ai4i+2020+predictive+maintenance+dataset.zip"
CWRU_URL = "https://engineering.case.edu/sites/default/files/{n}.mat"
IMS_URL = "https://phm-datasets.s3.amazonaws.com/NASA/4.+Bearings.zip"

# 12 kHz drive-end files used by ml/train_cwru.py (FILES: normal + 0.007" faults, loads 0-3 HP)
# and ml/test_cwru_severity.py (TEST_FILES: 0.014" and 0.021" faults). tests/test_download.py
# checks this list stays in sync with those scripts.
CWRU_FILES = [97, 98, 99, 100, 105, 106, 107, 108, 118, 119, 120, 121, 130, 131, 132, 133,
              169, 170, 171, 172, 185, 186, 187, 188, 197, 198, 199, 200,
              209, 210, 211, 212, 222, 223, 224, 225, 234, 235, 236, 237]
IMS_EXPECTED = 984                         # snapshots in test 2
IMS_NAME = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2}$")


# ------------------------------------------------------------------ download helper
def fetch(url: str, out: Path, label: str, retries: int = 3) -> Path:
    """Download to out (via a .part file, so an interrupted download never looks complete)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Indux-downloader/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done, last = 0, 0.0
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if time.time() - last > 1 or (total and done == total):
                        last = time.time()
                        pct = f"{100 * done / total:5.1f}%" if total else ""
                        print(f"\r  {label}: {done / 1e6:8.1f} MB {pct}", end="", flush=True)
            print()
            part.replace(out)
            return out
        except Exception as e:  # noqa: BLE001
            print(f"\n  {label}: attempt {attempt} failed ({e})")
            if attempt == retries:
                raise
            time.sleep(3 * attempt)
    return out


def human(n: float) -> str:
    return f"{n / 1e6:.1f} MB" if n < 1e9 else f"{n / 1e9:.2f} GB"


# ------------------------------------------------------------------ AI4I
def ai4i_ok(dest: Path) -> bool:
    f = dest / "ai4i" / "ai4i2020.csv"
    if not f.exists():
        return False
    with open(f, encoding="utf-8", errors="replace") as fh:
        head = fh.readline()
        rows = sum(1 for _ in fh)
    return "Machine failure" in head and rows == 10000


def get_ai4i(dest: Path):
    if ai4i_ok(dest):
        print("AI4I 2020: already there"); return
    print("AI4I 2020: downloading from UCI")
    zpath = fetch(AI4I_URL, dest / "ai4i" / "ai4i.zip", "ai4i.zip")
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.lower().endswith("ai4i2020.csv"))
        with z.open(name) as src, open(dest / "ai4i" / "ai4i2020.csv", "wb") as dst:
            shutil.copyfileobj(src, dst)
    print("AI4I 2020: OK" if ai4i_ok(dest) else "AI4I 2020: file looks wrong - delete data/benchmark/ai4i and retry")


# ------------------------------------------------------------------ CWRU
def cwru_ok(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 100_000:
        return False
    with open(path, "rb") as f:
        return f.read(6) == b"MATLAB"      # MAT-file v5 header


def get_cwru(dest: Path, files: list[int]):
    missing = [n for n in files if not cwru_ok(dest / "cwru" / f"{n}.mat")]
    print(f"CWRU: {len(files) - len(missing)} of {len(files)} files already there")
    for i, n in enumerate(missing, 1):
        out = dest / "cwru" / f"{n}.mat"
        fetch(CWRU_URL.format(n=n), out, f"[{i}/{len(missing)}] {n}.mat")
        if not cwru_ok(out):
            out.unlink(missing_ok=True)
            raise SystemExit(f"CWRU {n}.mat is not a MATLAB file - the site may have changed. "
                             f"Download it by hand from {CWRU_URL.format(n=n)}")
    if missing:
        print("CWRU: OK")


# ------------------------------------------------------------------ NASA IMS
def ims_count(dest: Path) -> int:
    d = dest / "ims" / "2nd_test"
    return sum(1 for p in d.iterdir() if IMS_NAME.match(p.name)) if d.is_dir() else 0


def _sevenzip() -> str | None:
    for c in ("7z", "7za", r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if shutil.which(c) or Path(c).exists():
            return shutil.which(c) or c
    return None


def _tar() -> str | None:
    win = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"   # bsdtar/libarchive
    return str(win) if win.exists() else shutil.which("bsdtar") or shutil.which("tar")


def unpack(archive: Path, into: Path) -> bool:
    """Extract .zip/.7z/.rar with whatever is available. Returns True on success."""
    into.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
        return True
    tried = []
    sz = _sevenzip()
    if sz:
        tried.append("7-Zip")
        if subprocess.run([sz, "x", "-y", f"-o{into}", str(archive)], capture_output=True).returncode == 0:
            return True
    tar = _tar()
    if tar:
        tried.append(f"tar ({tar})")
        if subprocess.run([tar, "-xf", str(archive), "-C", str(into)], capture_output=True).returncode == 0:
            return True
    try:
        if suffix == ".7z":
            import py7zr
            tried.append("py7zr")
            with py7zr.SevenZipFile(archive) as z:
                z.extractall(into)
            return True
        if suffix == ".rar":
            import rarfile
            tried.append("rarfile")
            with rarfile.RarFile(archive) as z:
                z.extractall(into)
            return True
    except Exception as e:  # noqa: BLE001  (ImportError or a missing unrar backend)
        tried.append(f"python packages failed: {type(e).__name__}")
    print(f"  could not unpack {archive.name} (tried: {', '.join(tried) or 'nothing available'})")
    return False


def _find_test2(root: Path) -> Path | None:
    """The folder holding test-2 snapshots (names like 2004.02.12.10.32.39)."""
    best = None
    for d in [root, *[p for p in root.rglob("*") if p.is_dir()]]:
        n = sum(1 for p in d.iterdir() if p.is_file() and IMS_NAME.match(p.name))
        if n and ("2nd" in d.name or "2nd" in str(d.parent)) and (best is None or n > best[1]):
            best = (d, n)
    return best[0] if best else None


def get_ims(dest: Path, keep: bool):
    have = ims_count(dest)
    if have >= IMS_EXPECTED:
        print(f"NASA IMS: already there ({have} snapshots)"); return
    work = dest / "ims" / "_download"
    zpath = work / "4_Bearings.zip"
    if not zpath.exists():
        free = shutil.disk_usage(dest).free
        print(f"NASA IMS: downloading 1.07 GB (then ~1.5 GB of temporary unpacking; {human(free)} free)")
        if free < 3e9:
            raise SystemExit("NASA IMS: needs about 3 GB free disk space. Free some space or use --only ai4i cwru.")
        fetch(IMS_URL, zpath, "4_Bearings.zip")
    stage = work / "unpacked"
    print("NASA IMS: unpacking (zip -> 7z -> rar) ...")
    unpack(zpath, stage)
    # unpack nested archives, the ones for test 2 first, until the snapshots appear
    for _ in range(4):
        if _find_test2(stage):
            break
        nested = sorted((p for p in stage.rglob("*") if p.suffix.lower() in (".7z", ".rar", ".zip")),
                        key=lambda p: ("2nd" not in p.name, p.name))
        nested = [p for p in nested if not (p.with_suffix("").exists())]
        if not nested:
            break
        for arc in nested:
            if arc.suffix.lower() == ".rar" and "2nd" not in arc.name:
                continue                     # tests 1 and 3 are not used
            if not unpack(arc, arc.with_suffix("")):
                return _ims_manual(work)
    src = _find_test2(stage)
    if not src:
        return _ims_manual(work)
    out = dest / "ims" / "2nd_test"
    out.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if IMS_NAME.match(p.name):
            shutil.move(str(p), out / p.name)
    print(f"NASA IMS: OK ({ims_count(dest)} snapshots in data/benchmark/ims/2nd_test)")
    if not keep:
        shutil.rmtree(work, ignore_errors=True)


def _ims_manual(work: Path):
    print("\nNASA IMS: automatic unpacking isn't possible on this machine. Do it by hand:\n"
          f"  1. Install 7-Zip (https://www.7-zip.org) - it opens both .7z and .rar - and re-run this script, or\n"
          f"  2. Open {work / '4_Bearings.zip'}, then IMS.7z inside it, then 2nd_test.rar, and copy the\n"
          f"     files named like 2004.02.12.10.32.39 into data/benchmark/ims/2nd_test/\n"
          f"  (The 1.07 GB download is kept in {work}, so it won't be downloaded again.)")


# ------------------------------------------------------------------ main
def check(dest: Path) -> bool:
    a = ai4i_ok(dest)
    c = sum(cwru_ok(dest / "cwru" / f"{n}.mat") for n in CWRU_FILES)
    i = ims_count(dest)
    print(f"AI4I 2020 : {'OK' if a else 'missing'}")
    print(f"CWRU      : {c} of {len(CWRU_FILES)} files")
    print(f"NASA IMS  : {i} of {IMS_EXPECTED} test-2 snapshots")
    return a and c == len(CWRU_FILES) and i >= IMS_EXPECTED


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", choices=["ai4i", "cwru", "ims"])
    ap.add_argument("--files", nargs="+", type=int, help="CWRU file numbers (default: all used by the scripts)")
    ap.add_argument("--check", action="store_true", help="only report what is present")
    ap.add_argument("--keep", action="store_true", help="keep the IMS download/unpack folder")
    ap.add_argument("--dest", type=Path, default=DEST, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    dest = args.dest.resolve()
    if args.check:
        return 0 if check(dest) else 1
    which = args.only or ["ai4i", "cwru", "ims"]
    if "ai4i" in which:
        get_ai4i(dest)
    if "cwru" in which:
        get_cwru(dest, args.files or CWRU_FILES)
    if "ims" in which:
        get_ims(dest, args.keep)
    print("\nNow run, for example:  python ml/eda.py   and   python ml/train_ai4i.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
