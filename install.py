"""각 레포에 릴리즈 알림을 설치한다.

하는 일(레포마다)
1. 기본 브랜치의 파일 트리에서 릴리즈 노트 파일을 찾는다. 없으면 건너뛴다.
2. 비밀값 SLACK_RELEASE_WEBHOOK 을 등록한다(값은 ~/.slack_release_webhook).
3. .github/workflows/release-notify.yml 을 GitHub API 로 커밋한다. 내용이 같으면 건너뛴다.

로컬 클론을 건드리지 않는다. 설치 커밋은 원격에만 생기므로 로컬은 다음에 pull 하면 된다.

실행
  python install.py                 # 대상 조회만(dry-run)
  python install.py --apply         # 설치
  python install.py --apply --secrets-only   # 웹훅 교체 시 비밀값만 다시 등록
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import subprocess
import sys

OWNER = "sym804"
REPOS = [
    "stockradar", "stockradar_us", "ym-testcase", "ym-wiki", "ym-blog", "sym804.github.io",
    "web_selector_extractor", "ai-squad", "card_checker", "couple-site", "claude-dotfiles",
    "suika-clone", "sym-ui", "qa-process-kit", "claude-config", "tc-eval", "ux-guard",
]
WORKFLOW_PATH = ".github/workflows/release-notify.yml"
SECRET = "SLACK_RELEASE_WEBHOOK"
WEBHOOK_FILE = pathlib.Path.home() / ".slack_release_webhook"
RELEASE_FILE_RE = re.compile(r"(^|/)release[_-]?notes?\.md$", re.IGNORECASE)
MARKER = "sym804/release-notify"   # 이 설치기가 쓴 워크플로라는 표지
TEMPLATE = pathlib.Path(__file__).with_name("caller-template.yml")
COMMIT_MSG = "ci: 릴리즈 노트 새 절 push 시 Slack 알림 워크플로 추가\n\nsym804/release-notify 의 공용 워크플로를 부른다."


def gh(*args: str, input: str | None = None, check: bool = True) -> str:
    r = subprocess.run(["gh", *args], input=input, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} 실패: {r.stderr.strip()[:300]}")
    return r.stdout


def release_files(repo: str, branch: str) -> list[str]:
    tree = json.loads(gh("api", f"repos/{OWNER}/{repo}/git/trees/{branch}?recursive=1"))
    if tree.get("truncated"):
        # 잘린 트리에서 못 찾은 것을 "없음"으로 읽으면 설치가 조용히 빠진다
        raise RuntimeError(f"{repo}: 파일 트리가 잘려 릴리즈 노트를 다 찾을 수 없다")
    return sorted(t["path"] for t in tree.get("tree", [])
                  if t["type"] == "blob" and RELEASE_FILE_RE.search(t["path"])
                  and "node_modules/" not in t["path"])


def render(branch: str, files: list[str]) -> str:
    # YAML 작은따옴표 안에서는 작은따옴표를 두 번 쓴다
    paths = "\n".join("      - '" + f.replace("'", "''") + "'" for f in files)
    return TEMPLATE.read_text(encoding="utf-8").replace("__BRANCH__", branch).replace("__PATHS__", paths)


def current_workflow(repo: str, branch: str) -> tuple[str | None, str | None]:
    r = subprocess.run(["gh", "api", f"repos/{OWNER}/{repo}/contents/{WORKFLOW_PATH}?ref={branch}"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        return None, None
    d = json.loads(r.stdout)
    return base64.b64decode(d["content"]).decode("utf-8"), d["sha"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--secrets-only", action="store_true")
    ap.add_argument("--repo", action="append", help="특정 레포만(여러 번 가능)")
    ap.add_argument("--force", action="store_true", help="표지가 없는 같은 이름 워크플로도 덮어쓴다")
    a = ap.parse_args()

    webhook = WEBHOOK_FILE.read_text(encoding="utf-8").strip() if WEBHOOK_FILE.exists() else ""
    if a.apply and not re.fullmatch(r"https://hooks\.slack\.com/services/\S+", webhook):
        print(f"웹훅 주소가 없거나 형식이 다르다: {WEBHOOK_FILE}")
        return 1

    for repo in a.repo or REPOS:
        branch = json.loads(gh("api", f"repos/{OWNER}/{repo}"))["default_branch"]
        files = release_files(repo, branch)
        if not files:
            print(f"- {repo}: 릴리즈 노트 없음, 건너뜀")
            continue
        content = render(branch, files)
        old, sha = current_workflow(repo, branch)
        state = "같음" if old == content else ("갱신" if old else "새로")
        foreign = old is not None and MARKER not in old
        if foreign:
            state = "다른 워크플로가 있음" + (", 덮어씀(--force)" if a.force else ", 건너뜀")
        print(f"- {repo} [{branch}] {', '.join(files)} / 워크플로 {state}")
        if foreign and not a.force:
            continue
        if not a.apply:
            continue
        gh("secret", "set", SECRET, "-R", f"{OWNER}/{repo}", input=webhook)
        if a.secrets_only or old == content:
            continue
        body = {"message": COMMIT_MSG, "branch": branch,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii")}
        if sha:
            body["sha"] = sha
        gh("api", "-X", "PUT", f"repos/{OWNER}/{repo}/contents/{WORKFLOW_PATH}", "--input", "-",
           input=json.dumps(body))
        print("  설치 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
