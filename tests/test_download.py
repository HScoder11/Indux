"""download_data.py: no network needed - checks the file list and the nested-archive unpacking."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ml"))          # the CWRU scripts import each other by bare name

import download_data as dd                     # noqa: E402


def test_cwru_list_matches_training_scripts():
    import test_cwru_severity
    import train_cwru
    assert sorted(dd.CWRU_FILES) == sorted({**train_cwru.FILES, **test_cwru_severity.TEST_FILES})


def test_ims_nested_archive_is_unpacked(tmp_path):
    """zip -> inner archive -> 2nd_test folder; a decoy 1st_test archive is ignored."""
    stage = tmp_path / "build"
    (stage / "2nd_test").mkdir(parents=True)
    for name in ("2004.02.12.10.32.39", "2004.02.12.10.42.39"):
        (stage / "2nd_test" / name).write_text("0.1 0.2 0.3 0.4\n")
    inner = stage / "2nd_test.zip"
    with zipfile.ZipFile(inner, "w") as z:
        for f in (stage / "2nd_test").iterdir():
            z.write(f, f"2nd_test/{f.name}")
    decoy = stage / "1st_test.zip"
    with zipfile.ZipFile(decoy, "w") as z:
        z.writestr("1st_test/2003.10.22.12.06.24", "x")

    dest = tmp_path / "dest"
    work = dest / "ims" / "_download"
    work.mkdir(parents=True)
    with zipfile.ZipFile(work / "4_Bearings.zip", "w") as z:
        z.write(inner, "4. Bearings/2nd_test.zip")
        z.write(decoy, "4. Bearings/1st_test.zip")

    dd.get_ims(dest, keep=False)
    got = sorted(p.name for p in (dest / "ims" / "2nd_test").iterdir())
    assert got == ["2004.02.12.10.32.39", "2004.02.12.10.42.39"]
    assert not work.exists()                   # temporary files cleaned up


def test_check_reports_missing(tmp_path, capsys):
    assert dd.main(["--check", "--dest", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "AI4I 2020 : missing" in out and "0 of 40" in out
