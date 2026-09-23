"""push 에서 릴리즈 노트에 새로 생긴 버전 절을 찾아 Slack 으로 알린다.

GitHub Actions 의 공용 워크플로(.github/workflows/notify.yml)가 부른다. 각 레포는
그 워크플로를 호출하는 파일 하나와 SLACK_RELEASE_WEBHOOK 비밀값만 가진다.

판정 규칙
- 이번 push 에서 바뀐 파일 중 이름이 release_note(s).md 계열인 것(대소문자 무관)
- 그 파일에서 릴리즈 후보를 뽑는다.
  - `##`/`###` 제목 중 버전 번호나 날짜가 든 것. 릴리즈 제목 아래 `###` 는 소제목이라 뺀다.
  - 첫 칸 머리글이 `버전` 인 표에서 첫 칸이 버전인 행(suika-clone 처럼 표에만 적는 레포).
- 후보마다 열쇠(버전과 짧은 이름표)를 만들고, push 이전보다 개수가 늘어난 것만 새 릴리즈로 본다.
  제목의 오타나 이슈 번호만 고친 push 는 알리지 않는다.
- 이전 파일이 없으면(처음 만든 릴리즈 노트) 맨 위 후보 하나만 알린다. 과거 이력 전체가
  한꺼번에 쏟아지지 않게 하기 위해서다.

실행: python notify.py --before SHA --after SHA --repo owner/name [--dry-run]
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass, field

RELEASE_FILE_RE = re.compile(r"(^|/)release[_-]?notes?\.md$", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")
H1_RE = re.compile(r"^#\s+\S")
ANY_HEADING_RE = re.compile(r"^(#{2,6})\s+(.*\S)\s*$")
# 버전(1.6.10.5, v0.8.23)과 날짜(2026-07-19). 표의 숫자나 소제목과 구분하는 표지다.
VERSION_RE = re.compile(r"(?<![\w.])v?\d+\.\d+(?:\.\d+)*(?![\w.])")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# 요약으로 쓸 소제목. 레포마다 이름이 다르다.
SUMMARY_SECTION_RE = re.compile(
    r"(변경|바뀐 것|수정|개선|고친 것|한 일|changed?|fixed|added|features?|what'?s new)", re.IGNORECASE)
# 요약 낱말이 들어 있어도 이것으로 시작하면 요약이 아니다("검증: 수정 확인", "남은 수정")
NOT_SUMMARY_HEAD_RE = re.compile(r"^(검증|qa|남은|남긴|테스트|알려진|안 한|안 고친)", re.IGNORECASE)
# 요약 소제목이 없을 때 첫 항목을 대신 쓰는데, 이 소제목 아래는 변경 내용이 아니라서 뺀다.
# 실측(커밋 303개): 남은 과제나 원인 분석이 변경 요약 자리에 나갔다.
NOT_SUMMARY_RE = re.compile(r"(검증|qa|남은|남긴|원인|배경|진단|이슈|알아낸|안 한|안 고친|영향|조치|참고|테스트)",
                            re.IGNORECASE)
# 표 행을 릴리즈로 보는 것은 첫 칸 머리글이 이것일 때뿐이다(suika-clone 의 "| 버전 | 날짜 | 요약 |").
TABLE_HEAD_RE = re.compile(r"^(버전|version|ver\.?|릴리즈|release)$", re.IGNORECASE)
BULLET_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d+\.)\s+(.*\S)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
TABLE_ROW_RE = re.compile(r"^\s*\|(.*)\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
RULE_RE = re.compile(r"^\s*(---|\*\*\*|___)\s*$")
ZERO_SHA = "0" * 40
MAX_ITEMS = 5
MAX_ITEM_CHARS = 160
MAX_RELEASES = 10
SIMILAR = 0.6   # 제목이 바뀐 절을 같은 절로 볼 본문 유사도
NL = chr(10)
MAX_MESSAGE_CHARS = 3500   # Slack 한 메시지 text 는 4,000자에서 잘린다


@dataclass
class Release:
    file: str
    heading: str
    items: list[str] = field(default_factory=list)


class _Fence:
    """코드 블록 안인지 추적한다. 여는 표지와 같은 표지로만 닫힌다."""

    def __init__(self) -> None:
        self.mark: str | None = None

    def step(self, line: str) -> bool:
        """이 줄을 건너뛰어야 하면 True(표지 줄 자체 포함)."""
        m = FENCE_RE.match(line)
        if m:
            if self.mark is None:
                self.mark = m.group(1)
            elif self.mark == m.group(1):
                self.mark = None
            return True
        return self.mark is not None


def _key(title: str) -> str:
    """같은 릴리즈일 수 있는 후보를 묶는 열쇠. 첫 버전, 버전이 없으면 첫 날짜.

    이름표(`시스템`, `Frontend`)는 넣지 않는다. 넣으면 `FE` 를 `Frontend` 로 고친 것만으로
    새 릴리즈가 된다. 같은 열쇠 안의 절은 find_new_releases 가 제목과 본문으로 짝짓는다.
    """
    m = VERSION_RE.search(title) or DATE_RE.search(title)
    return m.group(0).lstrip("v") if m else title.strip()


def _is_release_title(title: str) -> bool:
    return bool(VERSION_RE.search(title) or DATE_RE.search(title))


def _cells(line: str) -> list[str]:
    return [c.strip() for c in TABLE_ROW_RE.match(line).group(1).split("|")]


def _scan(text: str) -> list[tuple[int, str, int, str, list[str]]]:
    """릴리즈 후보 목록. (줄 번호, 종류, 제목 수준, 제목, 표 칸). 종류는 "h" 또는 "t".

    - 제목: `##`/`###` 중 버전이나 날짜가 있는 것. 단 상위 `##` 가 이미 릴리즈 제목이면
      그 아래 `###` 는 소제목이다. "WCAG 2.3.3" 같은 숫자가 든 소제목이 별도 릴리즈로 잡혔다.
    - 표 행: 첫 칸 머리글이 `버전` 인 표에서 첫 칸이 버전인 행.
    """
    lines = text.splitlines()
    out, fence, parent_rel, head_ok = [], _Fence(), False, False
    for i, line in enumerate(lines):
        if fence.step(line):
            continue
        if H1_RE.match(line):   # 새 문서 제목이면 상위 릴리즈 절도 끝난다
            parent_rel = False
            continue
        m = HEADING_RE.match(line)
        if m:
            lv, t = len(m.group(1)), m.group(2)
            rel = _is_release_title(t)
            if lv <= 2:
                parent_rel = rel
            if rel and (lv == 2 or not parent_rel):
                out.append((i, "h", lv, t, []))
            continue
        if not TABLE_ROW_RE.match(line):
            head_ok = False
            continue
        prev_is_row = i > 0 and TABLE_ROW_RE.match(lines[i - 1]) is not None
        if not prev_is_row:   # 표의 첫 줄 = 머리글
            head_ok = bool(TABLE_HEAD_RE.match(_cells(line)[0].strip("*` ")))
            continue
        if TABLE_SEP_RE.match(line) or not head_ok:
            continue
        cells = _cells(line)
        if VERSION_RE.fullmatch(cells[0].strip("*` ")):
            out.append((i, "t", 0, cells[0].strip("*` "), cells))
    return out


def _section_lines(lines: list[str], start: int, level: int) -> list[str]:
    """start 제목 아래부터 같은 수준 이상의 다음 제목이나 구분선(---) 직전까지."""
    body, fence = [], _Fence()
    for line in lines[start + 1:]:
        if fence.step(line):
            body.append(line)
            continue
        m = HEADING_RE.match(line)
        if (m and len(m.group(1)) <= level) or RULE_RE.match(line):
            break
        body.append(line)
    return body


def _clean(item: str) -> str:
    item = re.sub(r"\*\*(.+?)\*\*", r"\1", item)
    if len(item) <= MAX_ITEM_CHARS:
        return item
    cut = item[: MAX_ITEM_CHARS - 4]
    if cut.count("`") % 2:   # 잘린 자리가 코드 표기 안이면 닫아 준다. 안 닫으면 뒤 글자가 전부 코드로 보인다
        cut += "`"
    return cut + "..."


def summarize(section: list[str]) -> list[str]:
    """요약 소제목 아래 항목을 우선 쓰고, 없으면 절의 첫 항목들을 쓴다."""
    preferred, fallback, prose = [], [], []   # prose: 불릿이 없을 때 쓸 첫 문단 줄
    mode = "fallback"          # preferred / fallback / skip
    current: list[str] | None = None   # 마지막으로 연 항목. 줄바꿈으로 이어진 문장을 붙인다
    fence = _Fence()
    for line in section:
        if fence.step(line):
            current = None
            continue
        m = ANY_HEADING_RE.match(line)
        if m:
            title = m.group(2).strip()
            if SUMMARY_SECTION_RE.search(title) and not NOT_SUMMARY_HEAD_RE.match(title):
                mode = "preferred"
            elif NOT_SUMMARY_RE.search(title):
                mode = "skip"
            else:
                mode = "fallback"
            current = None
            continue
        b = BULLET_RE.match(line)
        if b:
            if mode == "skip":
                current = None
                continue
            target = preferred if mode == "preferred" else fallback
            target.append(b.group(1))
            current = target
            continue
        if not line.strip() or line.lstrip().startswith(("|", ">")):
            current = None
            continue
        if current is not None:   # 앞 항목이 다음 줄로 이어진 경우
            current[-1] += " " + line.strip()
        elif mode != "skip" and not prose and not line.startswith(("    ", "\t")):
            prose.append(line.strip())   # 들여쓴 줄은 코드나 표라서 뺀다
    # stockradar 는 절을 산문으로 써서 알림의 13% 가 제목만 나갔다
    items = preferred or fallback or prose
    return [_clean(i) for i in items[:MAX_ITEMS]]


def _table_release(file: str, cells: list[str]) -> Release:
    """표 행 하나를 릴리즈로. 제목은 버전(과 날짜), 요약은 가장 긴 칸."""
    ver = cells[0].strip("*` ")
    rest = [c for c in cells[1:] if c]
    date = next((c for c in rest if DATE_RE.fullmatch(c)), None)
    body = [c for c in rest if c != date]
    heading = f"{ver} ({date})" if date else ver
    items = [_clean(max(body, key=len))] if body else []
    return Release(file, heading, items)


def _candidates(text: str) -> list[tuple[int, str, int, str, list[str], str]]:
    """_scan 결과에 본문을 붙인다. (줄 번호, 종류, 수준, 제목, 표 칸, 본문).

    제목과 표에 같은 버전이 함께 있으면(stockradar 의 버전 매핑 표) 제목만 남긴다.
    """
    lines = text.splitlines()
    cands = _scan(text)
    head_versions = {m.group(0).lstrip("v") for c in cands if c[1] == "h" for m in VERSION_RE.finditer(c[3])}
    out = []
    for i, kind, lv, t, cells in cands:
        if kind == "t":
            if t.lstrip("v") in head_versions:
                continue
            body = " | ".join(cells[1:])
        else:
            body = NL.join(_section_lines(lines, i, lv))
        out.append((i, kind, lv, t, cells, body))
    return out


def _similar(a: str, b: str) -> bool:
    if a == b:
        return True
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sm.quick_ratio() >= SIMILAR and sm.ratio() >= SIMILAR


def find_new_releases(old_text: str | None, new_text: str, file: str) -> list[Release]:
    """old_text 에 없던 릴리즈를 new_text 에서 찾는다. old_text 가 None 이면 새 파일이다.

    같은 열쇠(_key) 안에서 짝을 짓는다.
    1. 제목이 그대로인 절은 이전 절과 같은 것이다.
    2. 남은 새 절은 제목이 바뀐 옛 절과 본문을 견준다. 비슷하면 제목만 고친 것이다
       (이슈 번호 교정 4d0ef31f, 엠대시 치환 e7054aa5, 이름표 변경 4ad07415).
    3. 짝이 없는 새 절이 새 릴리즈다. 같은 번호를 여러 절에 붙인 경우(stockradar 6.18.2.0)와
       한 절을 지우고 같은 번호로 다른 절을 쓴 경우도 여기서 잡힌다.
    """
    lines = new_text.splitlines()
    new = _candidates(new_text)
    if old_text is None:
        picked = new[:1]
    else:
        old_titles = Counter(c[3] for c in _candidates(old_text))
        removed: dict[str, list[str]] = {}   # 열쇠별로 제목이 사라진 옛 절의 본문
        new_titles = Counter(c[3] for c in new)
        for c in _candidates(old_text):
            if new_titles[c[3]] > 0:
                new_titles[c[3]] -= 1
            else:
                removed.setdefault(_key(c[3]), []).append(c[5])
        # 표 행은 옛 파일 어디에도(제목이든 행이든) 없던 버전일 때만 새 것이다.
        # 같은 버전의 제목 절을 지우자 표 행이 새 릴리즈로 잡혔다(ai-squad cf6d10e7)
        old_versions = {m.group(0).lstrip("v") for c in _scan(old_text) for m in VERSION_RE.finditer(c[3])}
        picked = []
        for c in new:
            if old_titles[c[3]] > 0:
                old_titles[c[3]] -= 1
                continue
            if c[1] == "t" and c[3].lstrip("v") in old_versions:
                continue
            pool = removed.get(_key(c[3]), [])
            match = next((j for j, body in enumerate(pool) if _similar(body, c[5])), None)
            if match is None:
                picked.append(c)
            else:
                pool.pop(match)
    out = []
    for i, kind, lv, t, cells, _ in picked:
        if kind == "t":
            out.append(_table_release(file, cells))
        else:
            out.append(Release(file, t, summarize(_section_lines(lines, i, lv))))
    return out


# ── git ─────────────────────────────────────────────────────────────

def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def _exists(sha: str) -> bool:
    return bool(sha) and sha != ZERO_SHA and _git("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def resolve_base(before: str, after: str) -> str | None:
    """비교 기준. 새 브랜치(before=0)나 강제 push 로 before 가 없으면 after 의 부모."""
    if _exists(before):
        return before
    parent = _git("rev-parse", "--verify", "--quiet", f"{after}^", check=False)
    return parent.stdout.strip() or None


def _show(sha: str, path: str) -> str | None:
    r = _git("show", f"{sha}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def collect(before: str, after: str) -> list[Release]:
    base = resolve_base(before, after)
    if base:
        names = _git("diff", "--name-only", base, after).stdout.splitlines()
    else:  # 첫 커밋
        names = _git("ls-tree", "-r", "--name-only", after).stdout.splitlines()
    releases: list[Release] = []
    for path in sorted(n for n in names if RELEASE_FILE_RE.search(n)):
        new = _show(after, path)
        if new is None:  # 이번 push 에서 지운 파일
            continue
        old = _show(base, path) if base else None
        releases += find_new_releases(old, new, path)
    return releases


# ── Slack ───────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_message(releases: list[Release], repo: str, server: str, sha: str) -> str:
    multi_file = len(set(x.file for x in releases)) > 1
    head = f"*{_esc(repo)}* 릴리즈"
    link = f"<{server}/{repo}/commit/{sha}|커밋 {sha[:7]}>"
    parts: list[str] = []
    for r in releases[:MAX_RELEASES]:
        block = [f"*{_esc(r.heading)}*"]
        if multi_file:
            block.append(f"_{_esc(r.file)}_")
        block += [f"• {_esc(i)}" for i in r.items]
        part = "\n".join(block)
        # 긴 메시지는 Slack 이 중간에서 자른다. 절 단위로 덜어 내고 남은 개수를 적는다
        room = MAX_MESSAGE_CHARS - 20 - len("\n\n".join([head, *parts, link])) - 2
        if len(part) > room:
            if not parts:   # 첫 릴리즈는 잘라서라도 넣는다. 통째로 빼면 가장 중요한 것이 사라진다
                parts.append(part[: max(room - 3, 0)] + "...")
            break
        parts.append(part)
    if len(parts) < len(releases):
        parts.append(f"외 {len(releases) - len(parts)}건")
    return "\n\n".join([head, *parts, link])


def post(webhook: str, text: str) -> None:
    req = urllib.request.Request(webhook, data=json.dumps({"text": text}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status != 200:
            raise RuntimeError(f"Slack 응답 {r.status}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default="")
    ap.add_argument("--after", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--server", default="https://github.com")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    releases = collect(a.before, a.after)
    if not releases:
        print("새 릴리즈 절 없음. 알림을 보내지 않는다.")
        return 0
    text = build_message(releases, a.repo, a.server, a.after)
    print(text)
    if a.dry_run:
        return 0
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        # 조용히 넘어가면 알림이 안 오는 이유를 아무도 모른다. job 을 빨갛게 둔다.
        print("SLACK_WEBHOOK_URL 이 비어 있다. 레포 비밀값 SLACK_RELEASE_WEBHOOK 을 확인할 것", file=sys.stderr)
        return 1
    post(webhook, text)
    print(f"알림 전송: {len(releases)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
