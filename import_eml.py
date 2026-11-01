"""Import .eml mail backups (e.g. Naver Mail / Cafe24 webmail zips) into Gmail with the Gmail API.

Run `python import_eml.py --help` for options. See README.md (users) and AGENTS.md (AI agents).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from email import policy
from email.parser import BytesHeaderParser, BytesParser
from pathlib import Path
from typing import Any, Iterable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload

try:
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError
except ImportError:  # keyring is optional; without it the login is kept in a user-only file.
    keyring = None
    KeyringError = PasswordDeleteError = Exception

# Google may return the granted scopes in a different order/format; they are verified explicitly below.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

MIN_PYTHON = (3, 10)
DEFAULT_SOURCE_DIR = "."
# Least privilege: add messages and manage labels only. No read, no send, no delete of mail.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.insert",
    "https://www.googleapis.com/auth/gmail.labels",
]
EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
SCOPES = GMAIL_SCOPES + ["openid", EMAIL_SCOPE]
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
KEYRING_SERVICE = "gmail-eml-import"
REVOKE_HINT = "https://myaccount.google.com/permissions"
API_RETRIES = 5
CSV_ENCODING = "utf-8-sig"
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
MAX_ZIP_ENTRY_BYTES = 200 * 1024 * 1024

EXIT_OK = 0
EXIT_PARTIAL_FAILURE = 1  # some files failed; the rest was imported
EXIT_USAGE = 2  # missing required option / safety flag / permission not ticked
EXIT_AUTH_EXPIRED = 3  # saved Google login expired or revoked
EXIT_ACCOUNT_MISMATCH = 4  # logged-in Gmail is not the expected one, or work folder belongs to another account
EXIT_ENVIRONMENT = 5  # setup problem: missing folder/credentials, another run in progress, unexpected error
EXIT_GMAIL_REFUSED = 6  # Gmail refused with a permission/quota error; stopped instead of failing every file

AUTH_EXPIRED_MESSAGE = (
    "Google 로그인 토큰이 만료되었거나 취소되었습니다. "
    "('테스트 중' 상태 앱의 토큰은 7일 뒤 만료됩니다.) "
    "`--mode logout`을 실행한 뒤 같은 명령을 다시 실행해 Google 로그인을 다시 하세요."
)
MISSING_SCOPE_MESSAGE = (
    "Google 권한 화면에서 필요한 권한이 모두 체크되지 않았습니다 "
    "(Gmail 편지함에 이메일 추가, 이메일 라벨 확인 및 수정). "
    '`--mode logout` 후 다시 실행해 "모두 선택"을 체크하세요.'
)


@dataclass
class RunResult:
    exit_code: int
    message: str
    total_files: int = 0
    imported_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


class AccountMismatchError(RuntimeError):
    pass


class MissingScopeError(RuntimeError):
    pass


class LockBusyError(RuntimeError):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import .eml mail backups into Gmail with the Gmail API (least-privilege OAuth).",
        epilog=(
            "exit codes: 0 ok, 1 some files failed, 2 usage/safety flag, 3 login expired, "
            "4 account mismatch, 5 setup/environment error, 6 Gmail refused (permission/quota)"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["extract", "dry-run", "whoami", "sample", "full", "forget-label", "logout"],
        default="dry-run",
    )
    parser.add_argument(
        "--source-dir",
        default=DEFAULT_SOURCE_DIR,
        help="Folder with .eml files (dry-run/sample/full), or a .zip file / folder of .zip files (extract).",
    )
    parser.add_argument("--output-dir", default=None, help="extract: where to unpack (default: <work folder>/extracted)")
    parser.add_argument("--label", default=None, help="Gmail label for the imported messages (required for sample/full).")
    parser.add_argument(
        "--expect-account",
        default=None,
        help="Gmail address that must be logged in (required for sample/full, checked by whoami). "
        "Import stops before writing if it differs.",
    )
    parser.add_argument("--limit", type=int, default=10, help="sample: number of messages (ignored by full)")
    parser.add_argument("--method", choices=["import", "insert"], default="import", help="Gmail API method (default: import)")
    parser.add_argument("--confirm-full-import", action="store_true")
    parser.add_argument("--confirm-forget", action="store_true")
    parser.add_argument(
        "--repair-malformed-headers",
        action="store_true",
        help="Only for files whose Date header cannot be parsed: repair a broken Received: continuation in the "
        "uploaded copy. Original .eml files are never changed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    if sys.version_info < MIN_PYTHON:
        print(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required.")
        return EXIT_ENVIRONMENT
    args = parse_args(argv)
    try:
        result = run(args, project_root=Path(__file__).resolve().parent)
    except LockBusyError as exc:
        result = RunResult(EXIT_ENVIRONMENT, str(exc))
    except Exception as exc:  # noqa: BLE001 - report a short, actionable line instead of a traceback.
        result = RunResult(EXIT_ENVIRONMENT, f"stopped: {type(exc).__name__}: {exc}")
    print(result.message)
    return result.exit_code


def configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def run(
    args: argparse.Namespace,
    *,
    project_root: Path,
    gmail_service: Any | None = None,
    account: str | None = None,
) -> RunResult:
    """Entry point used by main() and tests. Tests inject gmail_service and account."""
    project_root = project_root.resolve()
    logs_dir = project_root / "logs"
    state_dir = project_root / "state"
    logs_dir.mkdir(exist_ok=True)
    state_dir.mkdir(exist_ok=True)
    manifest_path = state_dir / "imported_manifest.json"

    if args.mode == "extract":
        output_dir = normalize_path(args.output_dir) if args.output_dir else project_root / "extracted"
        return extract_zips(normalize_path(args.source_dir), output_dir)
    if args.mode == "logout":
        removed = TokenStore(project_root).delete()
        return RunResult(
            EXIT_OK,
            f"logged out: removed saved login from {', '.join(removed) or 'nowhere (nothing saved)'}. "
            f"To revoke the app's access completely, remove 'gmail-eml-import' at {REVOKE_HINT}",
        )
    if args.mode == "forget-label":
        with WorkFolderLock(state_dir):
            return forget_label(args, manifest_path)
    if args.mode == "dry-run":
        source_dir = normalize_path(args.source_dir)
        return dry_run(find_eml_files(source_dir), logs_dir, report_suffix(source_dir))

    if args.mode in ("sample", "full"):
        if not args.label:
            return RunResult(EXIT_USAGE, "refusing import: --label is required for sample/full")
        if not args.expect_account:
            return RunResult(EXIT_USAGE, "refusing import: --expect-account <gmail address> is required for sample/full")
    if args.mode == "full" and not args.confirm_full_import:
        return RunResult(EXIT_USAGE, "refusing full import: pass --confirm-full-import only after manual Gmail verification")

    if gmail_service is None:
        try:
            gmail_service, account = build_gmail_service(
                project_root / "credentials.json",
                TokenStore(project_root),
                login_hint=args.expect_account,
            )
        except RefreshError:
            return RunResult(EXIT_AUTH_EXPIRED, AUTH_EXPIRED_MESSAGE)
        except MissingScopeError:
            return RunResult(EXIT_USAGE, MISSING_SCOPE_MESSAGE)
    account = (account or "").strip()
    print(f"Gmail account: {account or '(unknown)'}")

    manifest = load_manifest(manifest_path)
    if args.mode == "whoami":
        if args.expect_account:
            try:
                check_account(account, args.expect_account, manifest)
            except AccountMismatchError as exc:
                return RunResult(EXIT_ACCOUNT_MISMATCH, str(exc))
        return RunResult(EXIT_OK, f"logged in as {account} (nothing imported)")

    with WorkFolderLock(state_dir):
        manifest = load_manifest(manifest_path)
        try:
            check_account(account, args.expect_account, manifest)
        except AccountMismatchError as exc:
            return RunResult(EXIT_ACCOUNT_MISMATCH, str(exc))
        manifest["account"] = account.lower()
        save_manifest(manifest_path, manifest)
        source_dir = normalize_path(args.source_dir)
        return import_files(args, find_eml_files(source_dir), gmail_service, manifest, manifest_path, logs_dir)


class WorkFolderLock:
    """Prevents two imports from running in the same work folder at once (they would overwrite each other's records)."""

    def __init__(self, state_dir: Path):
        self.path = state_dir / ".lock"

    def __enter__(self) -> "WorkFolderLock":
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise LockBusyError(
                f"another run is using this work folder ({self.path}). Wait for it to finish. "
                "If nothing is running (e.g. the PC restarted mid-import), delete that file and retry."
            ) from None
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()} started={dt.datetime.now().isoformat(timespec='seconds')}\n")
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def check_account(account: str, expected: str, manifest: dict[str, Any]) -> None:
    if not account:
        raise AccountMismatchError("stopped before importing: could not read the logged-in Gmail address from Google.")
    if account.lower() != expected.strip().lower():
        raise AccountMismatchError(
            f"stopped before importing: logged in as {account}, but --expect-account is {expected}. "
            "Run `--mode logout`, then log in with the right account."
        )
    recorded = manifest.get("account", "")
    if recorded and recorded != account.lower():
        raise AccountMismatchError(
            f"stopped before importing: this work folder's state/ belongs to {recorded}, not {account}. "
            "Use a separate work folder for each Gmail account."
        )


def import_files(
    args: argparse.Namespace,
    eml_files: list[Path],
    gmail_service: Any,
    manifest: dict[str, Any],
    manifest_path: Path,
    logs_dir: Path,
) -> RunResult:
    label = args.label
    import_log = logs_dir / "import_log.csv"
    failed_log = logs_dir / "failed.csv"
    prepare_csv(import_log, IMPORT_LOG_FIELDS)
    prepare_csv(failed_log, FAILED_FIELDS)

    done = set(manifest["imported"].keys())
    skipped = imported = failed = 0
    sample_remaining = None
    if args.mode == "sample":
        sample_remaining = max(args.limit - count_manifest_label(manifest, label), 0)

    def result(code: int, prefix: str) -> RunResult:
        return RunResult(
            code,
            f"{prefix}imported={imported}, skipped={skipped}, failed={failed}, label={label}",
            total_files=len(eml_files),
            imported_count=imported,
            skipped_count=skipped,
            failed_count=failed,
        )

    def fail(path: Path, sha256: str, reason: str) -> None:
        nonlocal failed
        failed += 1
        append_row(failed_log, FAILED_FIELDS, {"path": str(path), "sha256": sha256, "label": label, "reason": reason})

    try:
        label_id = ensure_label(gmail_service, label)
    except RefreshError:
        return RunResult(EXIT_AUTH_EXPIRED, AUTH_EXPIRED_MESSAGE)
    except HttpError as exc:
        if http_status(exc) in (401, 403, 429):
            return RunResult(EXIT_GMAIL_REFUSED, f"stopped: Gmail refused label access: {short_http_error(exc)}")
        raise

    for path in eml_files:
        if sample_remaining is not None and imported >= sample_remaining:
            break
        sha256 = ""
        try:
            raw_bytes = path.read_bytes()
            sha256 = hashlib.sha256(raw_bytes).hexdigest()
            key = manifest_key(sha256, label)
            if key in done:
                skipped += 1
                continue
            done.add(key)
            metadata = read_headers(raw_bytes)
            header_repaired = False
            date_source = "header" if metadata["date"] else ""
            if not metadata["date"] and args.repair_malformed_headers:
                repaired = repair_malformed_headers(raw_bytes)
                repaired_metadata = read_headers(repaired)
                if repaired_metadata["date"]:
                    raw_bytes, metadata = repaired, repaired_metadata
                    header_repaired, date_source = True, "received"
        except Exception as exc:  # noqa: BLE001 - one broken file must not stop the whole mailbox.
            fail(path, sha256, f"cannot read/parse: {type(exc).__name__}: {str(exc)[:200]}")
            continue

        if not metadata["date"]:
            fail(path, sha256, "missing Date header")
            continue

        try:
            message_id = upload_message(gmail_service, raw_bytes, label_id=label_id, method=args.method)
        except RefreshError:
            return result(EXIT_AUTH_EXPIRED, f"{AUTH_EXPIRED_MESSAGE} stopped: ")
        except HttpError as exc:
            done.discard(key)
            if http_status(exc) in (401, 403, 429):
                return result(EXIT_GMAIL_REFUSED, f"stopped: Gmail refused ({short_http_error(exc)}). ")
            fail(path, sha256, f"HttpError: {short_http_error(exc)}")
            continue
        except Exception as exc:  # noqa: BLE001 - network errors etc.: record and continue.
            done.discard(key)
            fail(path, sha256, f"{type(exc).__name__}: {str(exc)[:300]}")
            continue

        imported += 1
        manifest["imported"][key] = {
            "sha256": sha256,
            "path": str(path),
            "gmail_message_id": message_id,
            "label": label,
            "method": args.method,
            "subject": metadata["subject"],
            "date": metadata["date"],
            "header_repaired": header_repaired,
            "date_source": date_source,
        }
        save_manifest(manifest_path, manifest)
        append_row(
            import_log,
            IMPORT_LOG_FIELDS,
            {
                "path": str(path),
                "sha256": sha256,
                "gmail_message_id": message_id,
                "label": label,
                "method": args.method,
                "date": metadata["date"],
                "from": metadata["from"],
                "to": metadata["to"],
                "subject": metadata["subject"],
                "message_id": metadata["message_id"],
                "header_repaired": str(header_repaired).lower(),
                "date_source": date_source,
            },
        )

    return result(EXIT_PARTIAL_FAILURE if failed else EXIT_OK, f"{args.mode} import finished: ")


def http_status(exc: HttpError) -> int:
    return int(getattr(getattr(exc, "resp", None), "status", 0) or 0)


def short_http_error(exc: HttpError) -> str:
    reason = exc._get_reason() if hasattr(exc, "_get_reason") else str(exc)  # noqa: SLF001 - public in practice
    return f"HTTP {http_status(exc)} {str(reason)[:200]}"


def forget_label(args: argparse.Namespace, manifest_path: Path) -> RunResult:
    """Remove one label's records from the local manifest so those files can be imported again.

    Gmail is not touched. Delete the already-imported messages in Gmail first.
    """
    if not args.label:
        return RunResult(EXIT_USAGE, "refusing forget-label: --label is required")
    manifest = load_manifest(manifest_path)
    keys = [key for key, item in manifest["imported"].items() if item.get("label") == args.label]
    if not args.confirm_forget:
        return RunResult(
            EXIT_USAGE,
            f"forget-label would remove {len(keys)} records for label {args.label!r}. "
            "Delete those messages in Gmail first, then re-run with --confirm-forget.",
        )
    if keys and manifest_path.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = manifest_path.with_name(f"imported_manifest.backup-{stamp}.json")
        backup.write_bytes(manifest_path.read_bytes())
    for key in keys:
        del manifest["imported"][key]
    save_manifest(manifest_path, manifest)
    return RunResult(EXIT_OK, f"forget-label removed {len(keys)} records for label {args.label!r} (backup kept in state/)")


def count_manifest_label(manifest: dict[str, Any], label: str) -> int:
    return sum(1 for item in manifest.get("imported", {}).values() if item.get("label") == label)


def manifest_key(sha256: str, label: str) -> str:
    # Per label: the same file in two mailboxes is imported once per label.
    return f"{sha256}|{label}"


# ---------------------------------------------------------------------------
# zip extraction (Naver backup zips store CP949 filenames without the UTF-8 flag)
# ---------------------------------------------------------------------------


def extract_zips(source: Path, output_root: Path) -> RunResult:
    if not source.exists():
        raise FileNotFoundError(f"zip file or folder not found: {source}")
    if source.is_file():
        zips = [source]
    else:
        zips = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() == ".zip")
    if not zips:
        return RunResult(EXIT_USAGE, f"no .zip files found in {source}")
    lines = []
    for zip_path in zips:
        target = output_root / safe_name(zip_path.stem)
        count = extract_zip(zip_path, target)
        lines.append(f"- {zip_path.name} -> {target} ({count})")
    return RunResult(EXIT_OK, "extracted:\n" + "\n".join(lines))


def safe_name(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/"))
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base).strip(" .") or "unnamed"
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    if len(base) > 120:
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
        stem = stem[:100] + "_" + digest
    return f"{stem}.{ext}" if ext else stem


def decode_zip_name(info: zipfile.ZipInfo) -> str:
    raw = info.filename.encode() if info.flag_bits & 0x800 else info.filename.encode("cp437")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="replace")


def extract_zip(zip_path: Path, final_dir: Path) -> str | int:
    """Unpack into <final_dir>.partial, verify the count, then rename and write .done. Never touches the zip."""
    if (final_dir / ".done").exists():
        return "already extracted"
    if final_dir.exists():
        shutil.rmtree(final_dir)
    tmp = final_dir.with_name(final_dir.name + ".partial")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as archive:
        items = [i for i in archive.infolist() if not i.is_dir()]
        for info in items:
            if info.file_size > MAX_ZIP_ENTRY_BYTES:
                raise ValueError(f"{zip_path.name}: entry too large ({info.file_size} bytes)")
            name = safe_name(decode_zip_name(info))
            target = tmp / name
            n = 2
            while target.exists():
                target = tmp / f"{Path(name).stem}_{n}{Path(name).suffix}"
                n += 1
            with archive.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
    count = sum(1 for p in tmp.iterdir() if p.is_file())
    if count != len(items):
        raise RuntimeError(f"{zip_path.name}: extracted {count} files but the zip has {len(items)}")
    tmp.rename(final_dir)
    (final_dir / ".done").write_text(str(count), encoding="utf-8")
    return count


# ---------------------------------------------------------------------------
# files, dry-run reports
# ---------------------------------------------------------------------------

WINDOWS_DRIVE_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def normalize_path(path_text: str) -> Path:
    """Accept both Windows (C:\\...) and WSL (/mnt/c/...) paths on either side."""
    text = path_text.strip().strip('"')
    if os.name == "nt" and text.startswith("/mnt/") and len(text) > 6:
        drive = text[5]
        rest = text[6:].replace("/", "\\")
        return Path(f"{drive.upper()}:\\{rest}")
    match = WINDOWS_DRIVE_PATH.match(text)
    if os.name != "nt" and match:
        rest = match.group(2).replace("\\", "/")
        return Path(f"/mnt/{match.group(1).lower()}/{rest}")
    return Path(text).expanduser()


def find_eml_files(source_dir: Path) -> list[Path]:
    if not source_dir.exists():
        raise FileNotFoundError(f"source directory not found: {source_dir}")
    return sorted(p for p in source_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".eml")


def report_suffix(source_dir: Path) -> str:
    name = re.sub(r"[^\w.-]+", "_", source_dir.resolve().name).strip("._")
    return name or "source"


def dry_run(eml_files: list[Path], logs_dir: Path, suffix: str) -> RunResult:
    rows = []
    errors = 0
    for path in eml_files:
        try:
            raw = path.read_bytes()
            rows.append(inspect_eml_bytes(raw, path=path, sha256=hashlib.sha256(raw).hexdigest()))
        except Exception as exc:  # noqa: BLE001 - report the broken file and keep going.
            errors += 1
            rows.append({"path": str(path), "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    write_csv(logs_dir / f"dry_run_report_{suffix}.csv", rows, DRY_RUN_FIELDS)
    write_duplicate_reports([row for row in rows if not row.get("error")], logs_dir, suffix)

    missing_date = sum(1 for row in rows if not row.get("error") and not row.get("date"))
    lines = [
        f"dry-run found {len(eml_files)} .eml files (unreadable={errors}, missing Date header={missing_date})",
        f"reports: logs/dry_run_report_{suffix}.csv, logs/duplicate_summary_{suffix}.json",
    ]
    return RunResult(EXIT_OK, "\n".join(lines), total_files=len(eml_files))


def write_duplicate_reports(rows: list[dict[str, Any]], logs_dir: Path, suffix: str) -> None:
    sha_groups = duplicate_groups(rows, "sha256")
    message_id_groups = duplicate_groups(rows, "message_id")
    duplicate_rows = []
    for reason, groups in (("sha256", sha_groups), ("message_id", message_id_groups)):
        for group_index, group_rows in enumerate(groups, start=1):
            keeper = choose_duplicate_keeper(group_rows)
            for row in group_rows:
                duplicate_rows.append(
                    {
                        "duplicate_reason": reason,
                        "duplicate_group": group_index,
                        "duplicate_count": len(group_rows),
                        "is_keeper": str(row["path"] == keeper["path"]).lower(),
                        **{field: row.get(field, "") for field in DRY_RUN_FIELDS},
                    }
                )
    write_csv(logs_dir / f"duplicate_report_{suffix}.csv", duplicate_rows, DUPLICATE_REPORT_FIELDS)
    summary = {
        "total_files": len(rows),
        "unique_sha256": len({row.get("sha256", "") for row in rows if row.get("sha256", "")}),
        "sha256_duplicate_groups": len(sha_groups),
        "sha256_duplicate_extra_files": sum(len(group) - 1 for group in sha_groups),
        "message_id_duplicate_groups": len(message_id_groups),
        "message_id_duplicate_extra_files": sum(len(group) - 1 for group in message_id_groups),
        "missing_message_id_files": sum(1 for row in rows if not row.get("message_id")),
        "note": "Import skips by (file SHA256, label) only. message_id duplicates are for reference.",
    }
    (logs_dir / f"duplicate_summary_{suffix}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def duplicate_groups(rows: list[dict[str, Any]], key: str) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        value = str(row.get(key, "")).strip().lower()
        if value:
            groups.setdefault(value, []).append(row)
    return [group for group in groups.values() if len(group) > 1]


def choose_duplicate_keeper(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(rows, key=lambda row: (len(str(row.get("path", ""))), str(row.get("path", "")).lower()))[0]


def inspect_eml_bytes(raw: bytes, *, path: Path, sha256: str) -> dict[str, Any]:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    return {
        "path": str(path),
        "sha256": sha256,
        "date": header_value(message["Date"]),
        "from": header_value(message["From"]),
        "to": header_value(message["To"]),
        "subject": header_value(message["Subject"]),
        "message_id": header_value(message["Message-ID"]),
        "has_attachments": str(has_attachments(message)).lower(),
        "size_bytes": len(raw),
        "error": "",
    }


def read_headers(raw: bytes) -> dict[str, str]:
    """Parse headers only (no body) to keep memory low during import."""
    message = BytesHeaderParser(policy=policy.default).parsebytes(raw)
    return {
        "date": header_value(message["Date"]),
        "from": header_value(message["From"]),
        "to": header_value(message["To"]),
        "subject": header_value(message["Subject"]),
        "message_id": header_value(message["Message-ID"]),
    }


def header_value(value: Any) -> str:
    return "" if value is None else str(value)


def has_attachments(message: Any) -> bool:
    for part in message.walk():
        disposition = (part.get_content_disposition() or "").lower()
        if disposition == "attachment" or part.get_filename():
            return True
    return False


# ---------------------------------------------------------------------------
# Google login
# ---------------------------------------------------------------------------


class TokenStore:
    """Keeps the Google login in the OS credential store (Windows Credential Manager, macOS Keychain,
    Linux Secret Service). Without one (e.g. WSL), it falls back to ~/.config/gmail-eml-import/ (0700/0600).

    Only the refresh token and scopes are stored; client id/secret are read from credentials.json.
    (Windows Credential Manager accepted about 1,000 but not 1,300 characters per entry in testing.)
    """

    def __init__(self, project_root: Path):
        folder_id = hashlib.sha256(str(project_root.resolve()).lower().encode("utf-8")).hexdigest()[:16]
        self.key = f"work-folder-{folder_id}"
        self.legacy_path = project_root / "token.json"  # written by older versions
        self.file_path = Path.home() / ".config" / "gmail-eml-import" / f"token-{folder_id}.json"

    def _keyring_get(self) -> str | None:
        if keyring is None:
            return None
        try:
            return keyring.get_password(KEYRING_SERVICE, self.key)
        except KeyringError:
            return None

    def _save_keyring(self, credentials: Credentials) -> bool:
        if keyring is None or not credentials.refresh_token:
            return False
        payload = json.dumps({"refresh_token": credentials.refresh_token, "scopes": list(credentials.scopes or [])})
        try:
            keyring.set_password(KEYRING_SERVICE, self.key, payload)
            return True
        except Exception:  # noqa: BLE001 - NoKeyringError, size limits, locked keychain ...
            return False

    def load(self, credentials_path: Path) -> Credentials | None:
        stored = self._keyring_get()
        if stored:
            client = json.loads(credentials_path.read_text(encoding="utf-8"))
            client = client.get("installed") or client.get("web") or {}
            data = json.loads(stored)
            return Credentials(
                token=None,
                refresh_token=data["refresh_token"],
                token_uri=client.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=client.get("client_id"),
                client_secret=client.get("client_secret"),
                scopes=data.get("scopes"),
            )
        for path in (self.file_path, self.legacy_path):
            if path.exists():
                credentials = Credentials.from_authorized_user_file(str(path))
                if path == self.legacy_path:
                    self.save(credentials)  # move it out of the work folder
                    print("moved the saved Google login out of token.json in the work folder.")
                return credentials
        return None

    def save(self, credentials: Credentials) -> None:
        if not self._save_keyring(credentials):
            print(
                "warning: no OS credential store is available here, so the Google login is saved in "
                f"{self.file_path} (your user only). Run `--mode logout` when you are done."
            )
            write_private_file(self.file_path, credentials.to_json().encode("utf-8"))
        else:
            self.file_path.unlink(missing_ok=True)
        if self.legacy_path.exists():
            self.legacy_path.unlink()

    def delete(self) -> list[str]:
        removed = []
        if keyring is not None:
            try:
                keyring.delete_password(KEYRING_SERVICE, self.key)
                removed.append("OS credential store")
            except (PasswordDeleteError, KeyringError):
                pass
        for path in (self.file_path, self.legacy_path):
            if path.exists():
                path.unlink()
                removed.append(str(path))
        return removed


def write_private_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def build_gmail_service(credentials_path: Path, store: TokenStore, *, login_hint: str | None = None) -> tuple[Any, str]:
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {credentials_path}. Create a Google Cloud Desktop OAuth client and place it there."
        )

    credentials = store.load(credentials_path)
    if credentials and not credentials.has_scopes(SCOPES):
        print("the saved Google login was created with different permissions; asking for a new Google login.")
        store.delete()
        credentials = None
    if credentials and not credentials.valid and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        print("OAuth browser authorization is about to open. Confirm the account and Gmail access manually.")
        extra = {"login_hint": login_hint} if login_hint else {}
        credentials = flow.run_local_server(port=0, **extra)
        granted = set(credentials.granted_scopes or credentials.scopes or [])
        if not set(GMAIL_SCOPES + [EMAIL_SCOPE]) <= granted:
            raise MissingScopeError(MISSING_SCOPE_MESSAGE)
        store.save(credentials)

    response = AuthorizedSession(credentials).get(USERINFO_URL, timeout=30)
    response.raise_for_status()
    account = response.json().get("email", "")
    return build("gmail", "v1", credentials=credentials), account


# ---------------------------------------------------------------------------
# Gmail API
# ---------------------------------------------------------------------------

BROKEN_RECEIVED_CONTINUATION = re.compile(rb"(?m)^(Received:\s+from[^\r\n]*\r?\n)(by\s+\S+\s+with\s+)")


def repair_malformed_headers(raw: bytes) -> bytes:
    return BROKEN_RECEIVED_CONTINUATION.sub(rb"\1 \2", raw, count=1)


def ensure_label(service: Any, label_name: str) -> str:
    existing = service.users().labels().list(userId="me").execute(num_retries=API_RETRIES).get("labels", [])
    for label in existing:
        if label.get("name") == label_name:
            return label["id"]
    body = {"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    return service.users().labels().create(userId="me", body=body).execute(num_retries=API_RETRIES)["id"]


def upload_message(service: Any, raw_bytes: bytes, *, label_id: str, method: str) -> str:
    # Media upload sends the original RFC 822 bytes as-is (no base64 copy in memory).
    media = MediaInMemoryUpload(raw_bytes, mimetype="message/rfc822", resumable=True)
    body = {"labelIds": [label_id]}
    messages = service.users().messages()
    if method == "import":
        request = messages.import_(
            userId="me", body=body, media_body=media, internalDateSource="dateHeader", neverMarkSpam=True
        )
    else:
        request = messages.insert(userId="me", body=body, media_body=media, internalDateSource="dateHeader")
    return request.execute(num_retries=API_RETRIES).get("id", "")


# ---------------------------------------------------------------------------
# state and logs
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"account": "", "imported": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("account", "")
    imported = data.setdefault("imported", {})
    # Older manifests used the bare SHA256 as key; convert to the per-label key.
    for key in list(imported.keys()):
        if "|" not in key:
            item = imported.pop(key)
            item.setdefault("sha256", key)
            imported[manifest_key(key, item.get("label", ""))] = item
    for item in imported.values():
        item.setdefault("date_source", "header" if item.get("date") else "")
    return data


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def csv_safe(value: Any) -> Any:
    """Prevent spreadsheet formula injection when logs are opened in Excel."""
    if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding=CSV_ENCODING) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: csv_safe(value) for key, value in row.items()} for row in rows)


def prepare_csv(path: Path, fields: list[str]) -> None:
    """Create the log with a header, or upgrade an older log's columns, before appending rows."""
    if not path.exists():
        write_csv(path, [], fields)
        return
    with path.open(newline="", encoding=CSV_ENCODING) as handle:
        reader = csv.DictReader(handle)
        if (reader.fieldnames or []) == fields:
            return
        existing_rows = list(reader)
    write_csv(path, existing_rows, fields)


def append_row(path: Path, fields: list[str], row: dict[str, Any]) -> None:
    with path.open("a", newline="", encoding=CSV_ENCODING) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writerow({key: csv_safe(value) for key, value in row.items()})


DRY_RUN_FIELDS = [
    "path",
    "sha256",
    "date",
    "from",
    "to",
    "subject",
    "message_id",
    "has_attachments",
    "size_bytes",
    "error",
]
DUPLICATE_REPORT_FIELDS = ["duplicate_reason", "duplicate_group", "duplicate_count", "is_keeper", *DRY_RUN_FIELDS]
IMPORT_LOG_FIELDS = [
    "path",
    "sha256",
    "gmail_message_id",
    "label",
    "method",
    "date",
    "from",
    "to",
    "subject",
    "message_id",
    "header_repaired",
    "date_source",
]
FAILED_FIELDS = ["path", "sha256", "label", "reason"]


if __name__ == "__main__":
    sys.exit(main())
