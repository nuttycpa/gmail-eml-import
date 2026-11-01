"""Offline tests: no Google login, no network. Run with `python -m pytest`."""

from __future__ import annotations

import csv
import json
import sys
import zipfile
from pathlib import Path

import httplib2
import pytest
from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_eml as m  # noqa: E402
from fakes import FakeGmailService  # noqa: E402

ME = "me@example.com"
GOOD = (
    b"Date: Mon, 1 Jan 2024 00:00:00 +0000\r\nFrom: a@example.com\r\nTo: b@example.com\r\n"
    b"Subject: =HYPERLINK(\"http://evil\")\r\nMessage-ID: <1@example.com>\r\n\r\nbody"
)


def args(**overrides):
    base = dict(
        mode="sample",
        source_dir="src",
        output_dir=None,
        label="L1",
        expect_account=ME,
        limit=10,
        method="import",
        confirm_full_import=False,
        confirm_forget=False,
        repair_malformed_headers=False,
    )
    base.update(overrides)
    return m.parse_args([]).__class__(**base)


@pytest.fixture()
def work(tmp_path: Path, monkeypatch) -> Path:
    # Which malformed headers crash Python's email parser differs between Python versions,
    # so simulate a parser crash for files containing the marker "BOOM".
    def crashing(original):
        def wrapper(raw, *a, **kw):
            if b"BOOM" in raw:
                raise IndexError("simulated parser crash")
            return original(raw, *a, **kw)
        return wrapper

    monkeypatch.setattr(m, "read_headers", crashing(m.read_headers))
    monkeypatch.setattr(m, "inspect_eml_bytes", crashing(m.inspect_eml_bytes))
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.eml").write_bytes(GOOD)
    (src / "b.EML").write_bytes(GOOD.replace(b"<1@", b"<2@"))
    (src / "c_broken.eml").write_bytes(b"X-Test: BOOM\r\nDate: Mon, 1 Jan 2024 00:00:00 +0000\r\n\r\nx")
    (src / "e_nodate.eml").write_bytes(b"Subject: x\r\n\r\nx")
    return tmp_path


def go(work: Path, svc=None, account: str | None = ME, **kw):
    a = args(source_dir=str(work / "src"), **kw)
    return m.run(a, project_root=work, gmail_service=svc or FakeGmailService(), account=account)


def manifest(work: Path) -> dict:
    return json.loads((work / "state" / "imported_manifest.json").read_text(encoding="utf-8"))


def test_dry_run_reports_broken_files_and_finds_upper_case_extension(work):
    r = m.run(args(mode="dry-run", source_dir=str(work / "src")), project_root=work)
    assert r.exit_code == 0 and r.total_files == 4
    assert "unreadable=1" in r.message and "missing Date header=1" in r.message
    assert (work / "logs" / "dry_run_report_src.csv").exists()


def test_required_options(tmp_path):
    assert m.run(args(label=None), project_root=tmp_path).exit_code == m.EXIT_USAGE
    assert m.run(args(expect_account=None), project_root=tmp_path).exit_code == m.EXIT_USAGE
    assert m.run(args(mode="full"), project_root=tmp_path).exit_code == m.EXIT_USAGE


def test_sample_imports_good_files_and_continues_past_broken_ones(work):
    svc = FakeGmailService()
    r = go(work, svc)
    assert r.exit_code == m.EXIT_PARTIAL_FAILURE
    assert (r.imported_count, r.failed_count) == (2, 2)
    assert "media_body" in svc.import_calls[0]
    assert manifest(work)["account"] == ME


def test_deeply_nested_header_does_not_stop_the_run(work):
    # Python may raise RecursionError on this header (depends on version/platform); either way the run must finish.
    (work / "src" / "f_nested.eml").write_bytes(b"To: " + b"(" * 5000 + b"\r\nDate: Mon, 1 Jan 2024 00:00:00 +0000\r\n\r\nx")
    r = go(work)
    assert r.exit_code in (m.EXIT_OK, m.EXIT_PARTIAL_FAILURE)
    assert r.imported_count + r.failed_count == 5


def test_rerun_skips_same_label_and_imports_again_for_another_label(work):
    svc = FakeGmailService()
    go(work, svc)
    again = go(work, svc, mode="full", confirm_full_import=True)
    assert (again.imported_count, again.skipped_count) == (0, 2)
    other = go(work, svc, mode="full", confirm_full_import=True, label="L2")
    assert other.imported_count == 2


def test_sample_limit(work):
    r = go(work, limit=1)
    assert r.imported_count == 1
    assert go(work, limit=1).imported_count == 0  # already has 1 for this label


@pytest.mark.parametrize("account", ["other@example.com", "", None])
def test_account_mismatch_or_unknown_stops_before_writing(work, account):
    svc = FakeGmailService()
    r = go(work, svc, account=account)
    assert r.exit_code == m.EXIT_ACCOUNT_MISMATCH
    assert svc.import_calls == [] and svc.labels == {}


def test_work_folder_bound_to_first_account(work):
    go(work)
    r = go(work, account="other@example.com", expect_account="other@example.com")
    assert r.exit_code == m.EXIT_ACCOUNT_MISMATCH


def test_whoami_checks_expected_account(work):
    assert go(work, mode="whoami", account="other@example.com").exit_code == m.EXIT_ACCOUNT_MISMATCH
    assert go(work, mode="whoami").exit_code == m.EXIT_OK


def test_lock_blocks_concurrent_run(work):
    (work / "state").mkdir(exist_ok=True)
    (work / "state" / ".lock").write_text("busy")
    with pytest.raises(m.LockBusyError):
        go(work)


def test_permission_error_stops_instead_of_failing_every_file(work):
    error = HttpError(httplib2.Response({"status": 403}), b'{"error": {"message": "insufficient"}}')
    r = go(work, FakeGmailService(upload_error=error))
    assert r.exit_code == m.EXIT_GMAIL_REFUSED and r.failed_count == 0


def test_forget_label_needs_confirmation_and_keeps_backup(work):
    go(work)
    assert m.run(args(mode="forget-label"), project_root=work).exit_code == m.EXIT_USAGE
    r = m.run(args(mode="forget-label", confirm_forget=True), project_root=work)
    assert r.exit_code == 0 and manifest(work)["imported"] == {}
    assert list((work / "state").glob("imported_manifest.backup-*.json"))


def test_old_manifest_keys_are_migrated(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"imported": {"abc": {"label": "L1", "date": "x"}}}), encoding="utf-8")
    assert list(m.load_manifest(path)["imported"]) == ["abc|L1"]


def test_csv_formula_injection_is_neutralised(work):
    go(work)
    with open(work / "logs" / "import_log.csv", encoding="utf-8-sig") as handle:
        subjects = [row["subject"] for row in csv.DictReader(handle)]
    assert subjects[0].startswith("'=")


def test_repair_malformed_headers_only_changes_upload_copy():
    raw = b"Received: from a.example\r\nby b.example with SMTP;\r\n Mon, 1 Jan 2024 00:00:00 +0000\r\n\r\nx"
    assert m.repair_malformed_headers(raw).startswith(b"Received: from a.example\r\n by b.example with ")


class Cp949ZipInfo(zipfile.ZipInfo):
    """Writes the name as raw CP949 without the UTF-8 flag, like Naver backup zips."""

    def _encodeFilenameFlags(self):  # noqa: N802 - overrides zipfile internals
        return "한글제목.eml".encode("cp949"), self.flag_bits


def test_extract_handles_cp949_names_duplicates_and_marks_done(tmp_path):
    zip_path = tmp_path / "id_보낸메일함.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(Cp949ZipInfo("korean.eml"), b"1")
        archive.writestr("a/x.eml", b"2")
        archive.writestr("b/x.eml", b"3")
        archive.writestr("../../evil.eml", b"4")
    r = m.run(args(mode="extract", source_dir=str(zip_path)), project_root=tmp_path)
    out = tmp_path / "extracted" / "id_보낸메일함"
    assert r.exit_code == 0 and (out / ".done").exists()
    assert sorted(p.name for p in out.iterdir()) == [".done", "evil.eml", "x.eml", "x_2.eml", "한글제목.eml"]
    again = m.run(args(mode="extract", source_dir=str(zip_path)), project_root=tmp_path)
    assert "already extracted" in again.message


def test_extract_refuses_oversized_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "MAX_ZIP_ENTRY_BYTES", 10)
    zip_path = tmp_path / "big.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("big.eml", b"0" * 100)
    with pytest.raises(ValueError):
        m.run(args(mode="extract", source_dir=str(zip_path)), project_root=tmp_path)
    assert not (tmp_path / "extracted" / "big" / ".done").exists()


@pytest.mark.skipif(m.os.name == "nt", reason="WSL-style conversion is for non-Windows")
def test_normalize_path_accepts_windows_paths():
    assert m.normalize_path(r'"C:\Users\me\mail"') == Path("/mnt/c/Users/me/mail")
