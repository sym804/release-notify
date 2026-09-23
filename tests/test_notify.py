"""notify.py 테스트. 실행: python -m pytest -q"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notify  # noqa: E402

NL = chr(10)


def md(*lines):
    return NL.join(lines) + NL


# ── 레포별 실제 형식 ────────────────────────────────────────────────

YM_TESTCASE_OLD = md(
    "# YM TestCase Release Notes",
    "## 현재 버전",
    "```",
    "YM TestCase System  v1.6.10.4  (2026-09-23)",
    "```",
    "---",
    "## v1.6.10.4 (2026-09-23) - [docs] 알려진 이슈와 Backlog 현행화",
    "### 이슈",
    "- 없음(문서만 변경)",
    "### 변경",
    "- 릴리즈 노트 하단 갱신",
)
YM_TESTCASE_NEW = YM_TESTCASE_OLD.replace(
    "## v1.6.10.4 (2026-09-23)",
    md(
        "## v1.6.10.5 (2026-09-23) - [fix] 우선순위 글자색 대비",
        "### 컴포넌트 버전",
        "| 컴포넌트 | 이전 | 이후 | 변경 |",
        "|---|---|---|---|",
        "| System | 1.6.10.4 | **1.6.10.5** | patch +1 |",
        "### 이슈",
        "- SYM-129 우선순위 글자색이 접근성 대비 기준에 못 미친다 (bug/minor/frontend)",
        "### 변경",
        "- 우선순위 색을 **테마 토큰**으로",
        "- 리포트 빈 값 표기 통일",
        "### 영향",
        "- 색이 조금 바뀐다",
        "---",
        "",
    ) + "## v1.6.10.4 (2026-09-23)",
).replace("v1.6.10.4  (2026-09-23)", "v1.6.10.5  (2026-09-23)")


def test_ym_testcase_형식에서_새_절만_찾는다():
    rs = notify.find_new_releases(YM_TESTCASE_OLD, YM_TESTCASE_NEW, "Release_note.md")
    assert [r.heading for r in rs] == ["v1.6.10.5 (2026-09-23) - [fix] 우선순위 글자색 대비"]
    # 요약은 "### 변경" 아래 항목이다. 이슈·영향·표는 들어가지 않는다
    assert rs[0].items == ["우선순위 색을 테마 토큰으로", "리포트 빈 값 표기 통일"]


def test_코드_블록_안의_버전은_제목이_아니다():
    rs = notify.find_new_releases(YM_TESTCASE_OLD, YM_TESTCASE_NEW, "Release_note.md")
    assert all("System  v1.6.10.5" not in r.heading for r in rs)


def test_세_단계_제목과_Fixed_소제목():
    # suika-clone(## + ### Fixed), web_v2(### v1.26.0.5 - 날짜)
    old = md("## 버전 현황", "### v1.26.0.4 - 2026-06-12", "- 이전")
    new = md("## 버전 현황", "### v1.26.0.5 - 2026-06-24", "#### Fixed", "- 차트 버그", "### v1.26.0.4 - 2026-06-12", "- 이전")
    rs = notify.find_new_releases(old, new, "web_v2/RELEASE_NOTES.md")
    assert [r.heading for r in rs] == ["v1.26.0.5 - 2026-06-24"]
    assert rs[0].items == ["차트 버그"]


def test_날짜만_있는_제목도_릴리즈다():
    # sym804.github.io
    old = md("## 2026-07-10 - 이전", "- a")
    new = md("## 2026-07-19 - 전 자산 수치 실측 통일", "### 배경", "- 수치가 과소 표기였다",
             "### 반영", "- 허브 수치를 실측값으로", "## 2026-07-10 - 이전", "- a")
    rs = notify.find_new_releases(old, new, "RELEASE_NOTES.md")
    assert [r.heading for r in rs] == ["2026-07-19 - 전 자산 수치 실측 통일"]
    assert rs[0].items == ["허브 수치를 실측값으로"]  # 요약 소제목이 없으면 배경 등을 뺀 첫 항목들


def test_컴포넌트_이름과_버전이_섞인_제목():
    # stockradar, couple-site, stockradar_us
    old = md("## 제품 버전 매핑", "| 2.17.0.1 | ... |")
    new = md("## 제품 버전 매핑", "| 2.17.1.0 | ... |", "| 2.17.0.1 | ... |",
             "## 시스템 2.17.1.0 / BE 4.11.0.1 - [feat] 레이트리밋 감시 (2026-09-23)", "### 변경", "- fail-open 감시")
    rs = notify.find_new_releases(old, new, "web/RELEASE_NOTES.md")
    assert [r.heading for r in rs] == ["시스템 2.17.1.0 / BE 4.11.0.1 - [feat] 레이트리밋 감시 (2026-09-23)"]


def test_버전이_없는_제목과_머리글이_버전이_아닌_표는_무시한다():
    old = md("## 매핑", "| 제품 | BE |", "|---|---|", "| 0.8.23 | 1.0 |")
    new = md("## 매핑", "| 제품 | BE |", "|---|---|", "| 0.8.24 | 1.1 |", "| 0.8.23 | 1.0 |", "## 알려진 이슈", "- x")
    assert notify.find_new_releases(old, new, "RELEASE_NOTES.md") == []


SUIKA_OLD = md(
    "# Release Notes",
    "",
    "| 버전 | 날짜 | 요약 |",
    "|---|---|---|",
    "| v0.1.17 | 2026-09-05 | E2E 가 14개 버전째 빨간불이던 것 수정. GH#1, GH#2 |",
    "| v0.1.16 | 2026-05-28 | 이모지가 원 위로 빠지던 문제 |",
)


def test_버전_표에_행만_더한_릴리즈도_잡는다():
    # suika-clone b018f730: 제목 없이 표 맨 위에 행 하나만 더한다
    new = SUIKA_OLD.replace(
        "|---|---|---|" + NL,
        "|---|---|---|" + NL + "| v0.1.18 | 2026-09-06 | deploy 를 수동 실행으로 제한. GH#3 |" + NL)
    rs = notify.find_new_releases(SUIKA_OLD, new, "RELEASE_NOTES.md")
    assert [(r.heading, r.items) for r in rs] == [("v0.1.18 (2026-09-06)", ["deploy 를 수동 실행으로 제한. GH#3"])]


def test_표_행의_글만_고치면_알리지_않는다():
    new = SUIKA_OLD.replace("이모지가 원 위로 빠지던 문제", "이모지 위치 수정")
    assert notify.find_new_releases(SUIKA_OLD, new, "RELEASE_NOTES.md") == []


def test_제목과_버전_표에_같은_버전이_있으면_한_번만():
    old = md("| 버전 | 요약 |", "|---|---|", "| 1.0.0 | a |", "## v1.0.0", "- a")
    new = md("| 버전 | 요약 |", "|---|---|", "| 1.1.0 | b |", "| 1.0.0 | a |", "## v1.1.0", "### 변경", "- b", "## v1.0.0", "- a")
    rs = notify.find_new_releases(old, new, "RELEASE_NOTES.md")
    assert [r.heading for r in rs] == ["v1.1.0"]


def test_제목_절을_지워도_남은_표_행을_새_릴리즈로_보지_않는다():
    # ai-squad cf6d10e7: "## v0.6.3" 절이 빠지고 요약표의 v0.6.3 행만 남았다
    table = md("| 버전 | 날짜 | 요약 |", "|---|---|---|", "| v0.6.3 | 2026-05-09 | readline 한계 수정 |")
    old = table + md("## v0.6.3 (2026-05-09)", "- readline 64KB 한계 수정")
    new = table + md("## v0.6.4 (2026-05-12)", "### 버그 수정", "- Phase 1 게이트")
    rs = notify.find_new_releases(old, new, "RELEASE_NOTES.md")
    assert [r.heading for r in rs] == ["v0.6.4 (2026-05-12)"]


def test_제목의_이슈_번호만_고치면_알리지_않는다():
    # stockradar_us 4d0ef31f
    old = md("## 시스템 1.37.2.0 - [fix] 종가 이력 삭제 (2026-08-31, us#250)", "- a")
    new = md("## 시스템 1.37.2.0 - [fix] 종가 이력 삭제 (2026-08-31, us#242)", "- a")
    assert notify.find_new_releases(old, new, "RELEASE_NOTES.md") == []


def test_같은_버전의_새_절이_기존_절_아래에_붙어도_새_절을_고른다():
    # stockradar_us: "시스템 1.47.0.0" 과 "Frontend 1.47.0.0" 이 따로 있다.
    # 새 절이 위에 붙으면 위에서부터 고르기만으로 맞으므로 일부러 아래에 붙인다
    old = md("## 시스템 1.47.0.0 / BE 1.43.0.0 - [feat] 시황 (2026-09-20)", "- 주간 시황 따라잡기")
    new = old + md("## Frontend 1.47.0.0 - [fix] 정렬 유실 (2026-09-21)", "- 뒤로가기 정렬 보존")
    rs = notify.find_new_releases(old, new, "RELEASE_NOTES.md")
    assert [(r.heading, r.items) for r in rs] == [("Frontend 1.47.0.0 - [fix] 정렬 유실 (2026-09-21)", ["뒤로가기 정렬 보존"])]


def test_이름표만_바꾸면_알리지_않는다():
    # couple-site 4ad07415, "v2 FE" -> "v2 Frontend"
    old = md("## v2 FE 1.40.1.0 - [feat] 트리맵 (2026-06-20)", "- 라벨 엔진 정돈", "- 자동 축소")
    new = md("## v2 Frontend 1.40.1.0 - [feat] 트리맵 (2026-06-20)", "- 라벨 엔진 정돈", "- 자동 축소")
    assert notify.find_new_releases(old, new, "RELEASE_NOTES.md") == []


def test_날짜만_있는_제목도_글만_고치면_알리지_않는다():
    # web_us e7054aa5: 엠대시를 하이픈으로 바꾼 것뿐인데 3건이 나갔다
    old = md("## 2026-04-15 (오후) " + chr(0x2014) + " 스크리너 정렬", "- 정렬 보존", "- 필터 보존")
    new = md("## 2026-04-15 (오후) - 스크리너 정렬", "- 정렬 보존", "- 필터 보존")
    assert notify.find_new_releases(old, new, "RELEASE_NOTES.md") == []


def test_같은_번호의_절을_지우고_다른_절을_쓰면_새_릴리즈다():
    # 두 QA 공통 지적: 개수만 보면 1 -> 1 이라 놓친다
    old = md("## 시스템 6.18.2.0 / 도구 - [fix] 슬롯 도구 (2026-08-19)", "- 결산월 날짜 처리")
    new = md("## 시스템 6.18.2.0 / 배치 - [enh] 배당 일정 (2026-08-19)", "- 배당 수집 간격을 주 1회로")
    rs = notify.find_new_releases(old, new, "RELEASE_NOTES.md")
    assert [r.heading for r in rs] == ["시스템 6.18.2.0 / 배치 - [enh] 배당 일정 (2026-08-19)"]


def test_문서_제목_아래의_세_단계_릴리즈_제목도_잡는다():
    new = md("## v1.0.0 (2026-01-01)", "- a", "# 부록", "### v2.0.0 (2026-02-01)", "- b")
    rs = notify.find_new_releases(md("## v1.0.0 (2026-01-01)", "- a"), new, "RELEASE_NOTES.md")
    assert [r.heading for r in rs] == ["v2.0.0 (2026-02-01)"]


def test_불릿이_없는_절은_첫_문단_줄을_요약으로_쓴다():
    # stockradar 는 "### 무엇을 했나" 아래를 산문과 들여쓴 표로 쓴다
    new = md("## 시스템 6.16.3.0 - [feat] 섹터 노트 (2026-08-15)", "### 배경", "질문에서 시작했다.",
             "### 무엇을 했나", "    10조 이상  85.5%", "대형주 중심 섹터 셋을 냈다.", "", "둘째 문단")
    rs = notify.find_new_releases(md("# t"), new, "RELEASE_NOTES.md")
    assert rs[0].items == ["대형주 중심 섹터 셋을 냈다."]


def test_같은_번호가_두_절에_붙어도_늘어난_만큼_알린다():
    # stockradar 6.18.2.0 이 같은 날 세 절에 붙었다
    old = md("## 시스템 6.18.2.0 / 배치 - [fix] a (2026-08-19)", "- a")
    new = md("## 시스템 6.18.2.0 / 배치 - [enh] b (2026-08-19)", "- b", *old.splitlines())
    rs = notify.find_new_releases(old, new, "RELEASE_NOTES.md")
    assert [r.heading for r in rs] == ["시스템 6.18.2.0 / 배치 - [enh] b (2026-08-19)"]


def test_릴리즈_절_안의_숫자_든_소제목은_별도_릴리즈가_아니다():
    # 10841666 류: "### WCAG 2.3.3 대응" 이 따로 알림이 됐다
    new = md("## v1.2.0 (2026-09-01)", "### WCAG 2.3.3 대응", "- 모션 끄기", "### R² 0.820 으로 개선", "- 모델")
    rs = notify.find_new_releases(md("# t"), new, "RELEASE_NOTES.md")
    assert [r.heading for r in rs] == ["v1.2.0 (2026-09-01)"]


def test_요약_소제목이_없으면_검증_원인_남은_절은_건너뛴다():
    new = md("## v1.0.0", "### 원인", "- 캐시가 낡았다", "### 검증", "- QA 통과", "### 남은 것", "- 나중에",
             "### 무엇을", "- 캐시 무효화 추가")
    rs = notify.find_new_releases(md("# t"), new, "RELEASE_NOTES.md")
    assert rs[0].items == ["캐시 무효화 추가"]


def test_원인과_수정_소제목은_요약으로_쓴다():
    # ai-squad 3ac6808a: "### 원인과 수정" 을 원인 절로 보고 건너뛰어 요약이 비었다
    new = md("## v0.8.20 (2026-07-13)", "### 원인과 수정", "- 타임아웃 배수 제거", "### 테스트", "- 12건 추가",
             "### 검증: 수정 확인", "- QA 통과")
    rs = notify.find_new_releases(md("# t"), new, "RELEASE_NOTES.md")
    assert rs[0].items == ["타임아웃 배수 제거"]


def test_물결표_코드_블록_안도_건너뛴다():
    new = md("## v1.0.0", "~~~", "## v9.9.9", "- 코드 속 항목", "~~~", "- 진짜 항목")
    rs = notify.find_new_releases(md("# t"), new, "RELEASE_NOTES.md")
    assert [(r.heading, r.items) for r in rs] == [("v1.0.0", ["진짜 항목"])]


def test_자를_때_백틱_짝을_맞춘다():
    item = "가" * 150 + " `" + "x" * 50 + "`"
    out = notify._clean(item)
    assert len(out) <= notify.MAX_ITEM_CHARS and out.count("`") % 2 == 0


def test_첫_릴리즈가_상한보다_길어도_잘라서_넣는다():
    r = notify.Release("R.md", "v9.9.9 " + "제" * 4000, ["a"])
    text = notify.build_message([r, notify.Release("R.md", "v9.9.8", [])], "sym804/x", "https://github.com", "a" * 40)
    assert len(text) <= notify.MAX_MESSAGE_CHARS
    assert "*v9.9.9 " in text and "외 1건" in text


def test_백틱으로_감싼_버전_머리글도_표로_본다():
    old = md("| `버전` | 요약 |", "|---|---|", "| 1.0.0 | a |")
    new = md("| `버전` | 요약 |", "|---|---|", "| 1.1.0 | b |", "| 1.0.0 | a |")
    assert [r.heading for r in notify.find_new_releases(old, new, "RELEASE_NOTES.md")] == ["1.1.0"]


def test_메시지_전체_길이에_상한이_있다():
    rs = [notify.Release("R.md", f"v1.{i}", ["가" * 150] * 5) for i in range(10)]
    text = notify.build_message(rs, "sym804/x", "https://github.com", "a" * 40)
    assert len(text) <= notify.MAX_MESSAGE_CHARS
    assert "외 " in text and text.endswith("|커밋 aaaaaaa>")


def test_새_파일이면_맨_위_절_하나만():
    new = md("## 0.2.1 (2026-09-23)", "- 새것", "## 0.2.0 (2026-08-07)", "- 옛것", "## 0.1.9 (2026-07-28)")
    rs = notify.find_new_releases(None, new, "RELEASE_NOTES.md")
    assert [r.heading for r in rs] == ["0.2.1 (2026-09-23)"]


def test_여러_줄에_걸친_항목은_한_항목으로_잇는다():
    # sym-ui 는 항목을 80자 근처에서 줄바꿈한다. 첫 줄만 잡으면 문장이 끊긴다
    new = md("## v0.13.0", "### 바뀐 것", "- 자립형 번들. 런타임 의존성을", "  번들에 넣었다.", "- 다음 항목", "", "본문 문단은 붙지 않는다")
    rs = notify.find_new_releases(md("# t"), new, "RELEASE_NOTES.md")
    assert rs[0].items == ["자립형 번들. 런타임 의존성을 번들에 넣었다.", "다음 항목"]


def test_요약은_5줄로_자르고_긴_줄은_줄인다():
    items = [f"- 항목 {i} " + "가" * 300 for i in range(8)]
    rs = notify.find_new_releases(md("# t"), md("# t", "## v1.0.0", "### 변경", *items), "RELEASE_NOTES.md")
    assert len(rs[0].items) == 5
    assert all(len(i) <= notify.MAX_ITEM_CHARS for i in rs[0].items)
    assert rs[0].items[0].endswith("...")


def test_메시지는_Slack_특수문자를_이스케이프한다():
    r = notify.Release("RELEASE_NOTES.md", "v1.0 <script>", ["a & b"])
    text = notify.build_message([r], "sym804/x", "https://github.com", "abcdef1234567")
    assert "&lt;script&gt;" in text and "a &amp; b" in text
    assert "<https://github.com/sym804/x/commit/abcdef1234567|커밋 abcdef1>" in text


def test_여러_파일이면_파일_이름을_붙인다():
    rs = [notify.Release("web/RELEASE_NOTES.md", "v1", []), notify.Release("web_v2/RELEASE_NOTES.md", "v2", [])]
    text = notify.build_message(rs, "sym804/stockradar", "https://github.com", "a" * 40)
    assert "_web/RELEASE_NOTES.md_" in text and "_web_v2/RELEASE_NOTES.md_" in text


# ── git 통합 ───────────────────────────────────────────────────────

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _commit(repo, path, text, msg="c"):
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def test_push_범위의_여러_커밋에서_새_절을_모은다(repo):
    base = _commit(repo, "RELEASE_NOTES.md", md("## 0.1.0 (2026-01-01)", "- a"))
    _commit(repo, "src.py", "x = 1")
    _commit(repo, "RELEASE_NOTES.md", md("## 0.2.0 (2026-02-01)", "### 변경", "- b", "## 0.1.0 (2026-01-01)", "- a"))
    head = _commit(repo, "RELEASE_NOTES.md", md("## 0.3.0 (2026-03-01)", "- c", "## 0.2.0 (2026-02-01)", "### 변경", "- b", "## 0.1.0 (2026-01-01)", "- a"))
    rs = notify.collect(base, head)
    assert [r.heading for r in rs] == ["0.3.0 (2026-03-01)", "0.2.0 (2026-02-01)"]


def test_릴리즈_노트를_안_건드린_push_는_알림이_없다(repo):
    base = _commit(repo, "RELEASE_NOTES.md", md("## 0.1.0", "- a"))
    head = _commit(repo, "src.py", "x = 1")
    assert notify.collect(base, head) == []


def test_before_가_0_이나_없는_커밋이면_마지막_커밋만_본다(repo):
    _commit(repo, "RELEASE_NOTES.md", md("## 0.1.0", "- a"))
    head = _commit(repo, "RELEASE_NOTES.md", md("## 0.2.0", "- b", "## 0.1.0", "- a"))
    for before in (notify.ZERO_SHA, "1234567890abcdef1234567890abcdef12345678"):  # 새 브랜치, 강제 push
        assert [r.heading for r in notify.collect(before, head)] == ["0.2.0"]


def test_첫_커밋이면_맨_위_절_하나만(repo):
    head = _commit(repo, "docs/Release_note.md", md("## v1.1.0", "- b", "## v1.0.0", "- a"))
    assert [r.heading for r in notify.collect(notify.ZERO_SHA, head)] == ["v1.1.0"]


def test_하위_폴더와_대소문자가_다른_파일명도_잡는다(repo):
    base = _commit(repo, "a.txt", "a")
    _commit(repo, "web_v2/release_notes.md", md("### v1.0.0 - 2026-01-01", "- a"))
    head = _commit(repo, "Release_Note.md", md("## v2.0.0", "- b"))
    files = sorted(r.file for r in notify.collect(base, head))
    assert files == ["Release_Note.md", "web_v2/release_notes.md"]


def test_dry_run_은_보내지_않고_출력만(repo, capsys, monkeypatch):
    base = _commit(repo, "RELEASE_NOTES.md", md("## 0.1.0", "- a"))
    head = _commit(repo, "RELEASE_NOTES.md", md("## 0.2.0", "- b", "## 0.1.0", "- a"))
    monkeypatch.setattr(notify, "post", lambda *a: pytest.fail("dry-run 인데 전송했다"))
    assert notify.main(["--before", base, "--after", head, "--repo", "sym804/x", "--dry-run"]) == 0
    assert "0.2.0" in capsys.readouterr().out


def test_웹훅이_비면_실패로_끝난다(repo, monkeypatch):
    # 조용히 성공하면 비밀값 누락을 아무도 모른다
    base = _commit(repo, "RELEASE_NOTES.md", md("## 0.1.0", "- a"))
    head = _commit(repo, "RELEASE_NOTES.md", md("## 0.2.0", "- b", "## 0.1.0", "- a"))
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert notify.main(["--before", base, "--after", head, "--repo", "sym804/x"]) == 1


def test_웹훅이_있으면_한_번_보낸다(repo, monkeypatch):
    base = _commit(repo, "RELEASE_NOTES.md", md("## 0.1.0", "- a"))
    head = _commit(repo, "RELEASE_NOTES.md", md("## 0.2.0", "- b", "## 0.1.0", "- a"))
    sent = []
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/x")
    monkeypatch.setattr(notify, "post", lambda url, text: sent.append(text))
    assert notify.main(["--before", base, "--after", head, "--repo", "sym804/x"]) == 0
    assert len(sent) == 1 and "0.2.0" in sent[0]
