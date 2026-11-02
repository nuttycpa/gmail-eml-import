<!-- AI agents (Claude Code, Codex, ...): read AGENTS.md first and follow it step by step. -->

# Gmail EML Import

**네이버 메일·웹메일에서 백업한 메일을 내 Gmail로 옮기는 무료 도구입니다.**
메일함을 백업하면 메일이 `.eml` 파일(zip 묶음)로 나오는데, 이 파일을 원본 그대로 Gmail에 넣습니다.
개발을 몰라도 AI 에이전트(Claude Code, Codex 등)에게 이 페이지 링크를 주면 진행해 줍니다.

> **이런 분께 맞습니다**
> - 네이버 메일 등에서 메일함을 백업(zip)할 수 있고, 그 메일을 Gmail에서 검색·보관하고 싶은 분
>
> **필요한 것**
> - Windows PC (Mac·Linux에서도 동작하도록 만들었지만, 실제 시험은 Windows에서 했습니다)
> - AI 에이전트: Claude Code·Codex 등 (에이전트 이용료는 별도)
> - 메일을 넣을 Gmail 계정, 그리고 백업 zip 합계보다 넉넉한 Gmail 남은 용량
>
> **비용·시간**
> - Google 쪽 비용 0원, 결제 정보 필요 없음
> - 처음 준비는 Google 설정(약 10분)을 포함해 30분 안팎으로 예상합니다. 넣는 시간은 메일 양에 따라 다르고, 끊겨도 이어서 진행됩니다.

## 특징

- **원본 그대로 들어갑니다.** 날짜·첨부파일·보낸사람·받는사람·본문이 바뀌지 않습니다. (Gmail에 넣은 메일을 다시 내려받아 원본 파일과 비교해 확인했습니다.)
- **메일을 읽거나 보낼 권한이 없습니다.** Google 권한 화면에는 "Gmail 편지함에 이메일 추가", "이메일 라벨 확인 및 수정" 두 항목만 나옵니다. ("라벨 확인"은 메일함 이름 목록을 보는 것이고 메일 내용을 읽는 권한이 아닙니다.)
- **앱 비밀번호가 필요 없습니다.** Google 로그인 화면에서 승인만 합니다.
- **Outlook 같은 메일 프로그램이나 IMAP 설정이 필요 없습니다.** 백업 zip만 있으면 됩니다.
- **10통 먼저 넣고 확인**한 뒤에 전체를 넣습니다. 로그인한 계정이 지정한 계정과 다르면 넣기 전에 멈춥니다.
- **중간에 끊겨도 이어서** 진행하고, 이미 넣은 메일은 다시 넣지 않습니다.

### 앱 비밀번호 없이 어떻게 Gmail에 넣나요?

- 웹사이트에서 "Google 계정으로 로그인"을 누를 때와 같은 Google 공식 로그인 방식(OAuth)을 씁니다.
- 실행하면 브라우저에 Google 로그인 화면이 뜹니다. 로그인과 승인은 Google 화면에서 하고, 이 도구는 비밀번호를 보거나 저장하지 않습니다.
- 승인하면 Google이 "메일 추가·라벨 관리·이메일 주소 확인"만 되는 출입증(토큰)을 줍니다. 이 출입증은 Windows 자격 증명 관리자(Mac은 키체인)에 보관됩니다.
- 이 방식을 쓰려면 "이 도구가 내 Gmail에 메일을 넣어도 된다"는 등록을 Google에 한 번 해야 합니다. 그게 아래 3단계의 credentials.json 만들기(약 10분)입니다. 앱 비밀번호를 만드는 대신 이 등록을 하는 셈입니다.

## 1. 메일 백업 받기 (zip 다운로드)

옮기고 싶은 **메일함을 전부** 백업합니다. 메일함마다 zip 파일이 하나씩 나옵니다.
받은메일함·보낸메일함 말고 직접 만든 메일함이 있으면 그것도 백업하세요. 백업하지 않은 메일함은 옮겨지지 않습니다.

- **네이버 메일**: 환경설정 > 메일함 관리 > 메일함별 [백업] → zip 다운로드 (예: `아이디_받은메일함.zip`, `아이디_보낸메일함.zip`)
- **카페24 등 다른 웹메일**: 메일함 관리 메뉴에 백업(EML 내려받기) 기능이 있는지 확인하세요. 이 도구를 만들면서 카페24의 메뉴 위치는 직접 확인하지 못했습니다.
- zip을 열었을 때 `.eml` 파일들이 보이면 됩니다. `.pst`, `.mbox` 같은 다른 형식은 지원하지 않습니다.

zip은 압축을 풀지 말고 **다운로드 폴더에 받은 그대로** 두면 됩니다.

## 2. AI 에이전트에게 맡기기

Claude Code·Codex 등에 아래 문장을 붙여넣으세요. 이메일 주소만 본인 것으로 바꾸면 됩니다.

```text
https://github.com/nuttycpa/gmail-eml-import
이 repo의 AGENTS.md 순서대로 내 네이버 메일 백업을 Gmail로 옮겨줘.
백업 zip 파일은 다운로드 폴더에 있고, 넣을 Gmail 계정은 내주소@gmail.com 이야.
```

- 다른 폴더에 두었다면 탐색기 주소창을 클릭해 나온 경로를 복사해서 "다운로드 폴더" 대신 붙여넣으세요.
- 진행 중 에이전트가 **"이 명령을 실행해도 될까요?"라고 여러 번 묻습니다.** Python 설치, 이 도구 내려받기, 압축 풀기, `import_eml.py` 실행은 허용하세요. 원본 zip을 지우거나 작업 폴더 밖의 파일을 바꾸겠다고 하면 거절하세요.
- Python이 없으면 에이전트가 설치해도 되는지 먼저 묻습니다.

## 3. credentials.json 만들기 (Gmail 접근 등록)

메일을 넣을 Gmail 계정으로 **본인이 직접** 만듭니다. 10분 정도 걸리고 비용은 들지 않습니다.
[CREATE_CREDENTIALS_STEP_BY_STEP.md](CREATE_CREDENTIALS_STEP_BY_STEP.md) 를 따라 하세요. 에이전트가 압축 풀기와 사전 점검을 하는 동안 해도 됩니다.

- 마지막에 JSON 파일을 **다운로드만** 하고 에이전트에게 "다운로드했어"라고 말하면 됩니다.
- 개인 Gmail(@gmail.com)이면 "대상: 외부"로 만들고, **본인 이메일을 테스트 사용자로 등록**해야 합니다. 프로젝트를 만든 계정이라도 테스트 사용자로 등록해야 로그인됩니다.

## 4. 로그인과 10통 확인

처음 실행하면 브라우저에 Google 화면이 차례로 뜹니다. 모두 정상입니다.

1. **계정 선택**: 메일을 넣을 계정을 고릅니다.
2. **"Google에서 확인하지 않은 앱"** 경고: 방금 내가 만든 앱이라 Google 심사를 받지 않아 뜨는 화면입니다. 앱 이름이 내가 정한 이름(`gmail-eml-import`)이면 "계속"을 누릅니다.
3. **이메일 주소 확인**: "계속".
4. **권한 선택**: 체크박스가 꺼져 있습니다. **"모두 선택"을 체크**하고 "계속".
5. "The authentication flow has completed"가 나오면 창을 닫아도 됩니다.

그다음 에이전트가 메일 10통만 먼저 넣고 멈춥니다. Gmail 왼쪽 라벨(메일함 이름)을 열어 날짜·첨부파일·한글이 맞는지 보고 "OK"라고 답하면 나머지를 넣습니다.

## Gmail에서 보이는 위치

- 가져온 메일은 Gmail 왼쪽 **라벨**(메일함 이름)에서 보입니다.
- Gmail의 받은편지함·보낸편지함에는 나타나지 않습니다. Gmail API는 가져온 메일에 '보낸편지함' 표시를 붙이는 것을 허용하지 않습니다.
- 가져오기는 메일을 다시 보내지 않습니다. 상대방에게 아무것도 발송되지 않습니다.

## 되돌리기 (10통 확인 결과가 이상할 때)

1. Gmail에서 그 라벨을 열고 → 전체 선택 → 삭제(휴지통)합니다. Google 고객센터 설명대로 "이메일을 삭제하면 해당 이메일은 모든 라벨과 받은편지함에서 삭제됩니다."
2. 에이전트에게 "그 라벨 기록도 지워줘"라고 말합니다. 그래야 다시 넣을 수 있습니다.

## 다 옮긴 뒤

- 에이전트가 저장된 로그인 정보를 지웁니다.
- 그다음 **직접** https://myaccount.google.com/permissions 에 들어가 `gmail-eml-import`를 찾아 접근을 삭제하세요.

## 나중에 메일을 더 옮길 때

- 새 zip을 받고 에이전트에게 "전에 쓴 gmail-eml-import 폴더로 이어서 해줘"라고 말하세요. 같은 폴더를 써야 이미 넣은 메일을 건너뜁니다.
- 로그인과 "확인하지 않은 앱" 화면이 다시 나오는데 정상입니다. credentials.json은 다시 만들 필요가 없습니다.
- 다른 Gmail 계정에 넣을 때는 에이전트가 작업 폴더를 따로 만듭니다.

## 개인정보와 안전

- **메일 원문은 내 PC에서 Google로만 갑니다.** 다른 회사 서버를 거치지 않습니다.
- 다만 **AI 에이전트가 진행을 맡으므로, 에이전트가 보는 파일 이름·건수·오류 메시지는 그 AI 서비스에 전달됩니다.** 네이버 백업 파일 이름에는 메일 제목이 들어 있습니다. 에이전트는 메일 본문과 로그 내용을 열어 보지 않도록 지시받습니다(AGENTS.md).
- 원본 zip·EML 파일은 수정·삭제·이동하지 않습니다.
- `credentials.json`은 남에게 보내지 마세요.
- 같은 메일을 다시 넣었을 때 Gmail은 복사본을 만들지 않고 기존 메일을 그대로 두었습니다(실측 4건).

## 다른 방법과 무엇이 다른가

| 방법 | 대상 | 이 도구와 다른 점 |
|---|---|---|
| 상용 EML→Gmail 변환 프로그램 | EML | 유료(무료판은 25통 제한 사례). 메일 계정 접근을 판매사 프로그램에 맡김 |
| Thunderbird·Outlook에 Gmail 연결 후 끌어다 놓기 | EML | 메일 프로그램 설치, Gmail IMAP 설정, 앱 비밀번호 필요. 수동 작업 |
| [google/import-mailbox-to-gmail](https://github.com/google/import-mailbox-to-gmail) | mbox | 회사 Workspace 관리자용(서비스 계정). 개인 Gmail·EML 대상 아님 |
| [GYB](https://github.com/GAM-team/got-your-back) | mbox | Gmail에서 내보낸 mbox를 되돌리는 용도 |
| [upload-eml-to-gmail-nodejs](https://github.com/eriktodx/upload-eml-to-gmail-nodejs) | EML | IMAP + 앱 비밀번호를 설정 파일에 저장. Node.js와 설정 작성 필요 |
| [gmail-migration-tools](https://github.com/MadanChaollaPark/gmail-migration-tools) | EML | macOS·Linux 전용(Windows 불가), 설정 파일을 직접 쓰는 개발자용. 메일 읽기 권한도 요청 |

(2026-11 기준, 각 저장소의 README·코드와 판매사 페이지를 확인했습니다. 다른 도구가 원본을 그대로 보존하는지는 확인하지 않았습니다.)

---

## 개발자용: 에이전트 없이 쓰기

**요구 사항**: Python 3.10 이상. 실제 Gmail 시험은 Windows, 오프라인 테스트는 Windows·WSL(Linux)에서 했습니다.

```bash
git clone https://github.com/nuttycpa/gmail-eml-import
cd gmail-eml-import
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows (macOS/Linux: .venv/bin/python)
```

`credentials.json`(Google Cloud "데스크톱 앱" OAuth 클라이언트)을 이 폴더에 둔 뒤:

```bash
python import_eml.py --mode extract --source-dir ~/Downloads/아이디_보낸메일함.zip
python import_eml.py --mode dry-run --source-dir extracted/아이디_보낸메일함
python import_eml.py --mode whoami  --expect-account me@gmail.com
python import_eml.py --mode sample  --source-dir extracted/아이디_보낸메일함 --label 보낸메일함 --expect-account me@gmail.com --limit 10
python import_eml.py --mode full    --source-dir extracted/아이디_보낸메일함 --label 보낸메일함 --expect-account me@gmail.com --confirm-full-import
python import_eml.py --mode logout
```

| 모드 | 하는 일 | Gmail 쓰기 |
|---|---|---|
| `extract` | zip(파일 또는 zip이 든 폴더)을 `extracted/<zip 이름>/`에 풂. CP949 파일명 처리, 개수 검증 후 `.done` 표시 | 없음 |
| `dry-run` | `.eml` 개수·읽기 오류·날짜 없음 점검, `logs/dry_run_report_<폴더>.csv` | 없음 |
| `whoami` | 로그인하고 계정만 출력. `--expect-account`와 다르면 종료코드 4 | 없음 |
| `sample` | `--limit`통만 import (이 라벨로 이미 넣은 수는 빼고 셈) | 있음 |
| `full` | 전부 import. `--confirm-full-import` 필수 | 있음 |
| `forget-label` | 로컬 기록에서 한 라벨 기록 삭제(백업 후). `--confirm-forget` 필수. Gmail은 건드리지 않음 | 없음 |
| `logout` | 저장된 로그인 삭제 | 없음 |

- **권한(scope)**: `gmail.insert`, `gmail.labels`, `openid`, `userinfo.email`. 메일 읽기·삭제·발송 권한 없음.
- **로그인 저장**: `keyring`으로 OS 보관함(Windows 자격 증명 관리자, macOS 키체인, Linux Secret Service)에 refresh token과 scope만 저장. 보관함이 없으면 `~/.config/gmail-eml-import/token-<id>.json`(0600).
- **파일 위치**(모두 `import_eml.py`가 있는 폴더 기준): `credentials.json`, `extracted/`, `state/imported_manifest.json`(가져온 기록), `logs/`(`import_log.csv`, `failed.csv`, dry-run 보고서).
- **중복 판단**: 같은 작업 폴더 안에서 (원본 파일 SHA256, 라벨) 조합이 기록에 있으면 건너뜀. 작업 폴더는 처음 쓴 Gmail 계정에 묶임.
- **업로드**: `users.messages.import`(media upload, `internalDateSource=dateHeader`, `neverMarkSpam`). 원본 바이트를 그대로 보냄. `--repair-malformed-headers`는 Date를 못 읽는 파일에서만 업로드용 사본의 `Received:` 줄 하나를 고침.
- **동시 실행 방지**: 실행 중 `state/.lock`. 비정상 종료 후 남아 있으면 지우고 다시 실행.
- **재시도**: API 호출마다 최대 5회 재시도. 401·403·429가 계속되면 파일마다 실패시키지 않고 멈춤(종료코드 6).

| 종료코드 | 뜻 |
|---|---|
| 0 | 성공 |
| 1 | 일부 파일 실패(나머지는 들어감, `logs/failed.csv`) |
| 2 | 필수 옵션·확인 플래그 없음, 권한 미체크 |
| 3 | 로그인 만료·취소 (`--mode logout` 후 재로그인) |
| 4 | 계정 불일치(지정 계정과 다름, 또는 다른 계정용 작업 폴더) |
| 5 | 설정·환경 오류(폴더·credentials 없음, 다른 실행 중 등) |
| 6 | Gmail이 권한·한도 오류로 거부해 중단 |

**테스트**(오프라인, Google 로그인 없음):

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

## 만든 사람

[NuttyCPA](https://www.nuttycpa.com) · MIT License ([LICENSE](LICENSE))
