"""install.py 테스트. gh 호출은 가짜로 바꾼다."""
import base64
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import install  # noqa: E402


def test_경로의_작은따옴표는_YAML_규칙대로_두_번_쓴다():
    out = install.render("main", ["it's/RELEASE_NOTES.md"])
    assert "      - 'it''s/RELEASE_NOTES.md'" in out
    assert "branches: [main]" in out and install.MARKER in out


def test_잘린_트리는_없음으로_읽지_않고_멈춘다(monkeypatch):
    monkeypatch.setattr(install, "gh", lambda *a, **k: json.dumps({"tree": [], "truncated": True}))
    with pytest.raises(RuntimeError, match="잘려"):
        install.release_files("x", "main")


def test_node_modules_안의_릴리즈_노트는_뺀다(monkeypatch):
    tree = {"tree": [{"type": "blob", "path": "RELEASE_NOTES.md"},
                     {"type": "blob", "path": "node_modules/a/release-notes.md"},
                     {"type": "tree", "path": "docs/RELEASE_NOTES.md"}], "truncated": False}
    monkeypatch.setattr(install, "gh", lambda *a, **k: json.dumps(tree))
    assert install.release_files("x", "main") == ["RELEASE_NOTES.md"]


WEBHOOK = "https://hooks.slack.com/services/T/B/secret-value"


def _fake(monkeypatch, old_workflow, tmp_path):
    calls = []
    hook = tmp_path / "hook"
    hook.write_text(WEBHOOK, encoding="utf-8")
    # 경로만 바꿔 끼운다. read_text 를 통째로 바꾸면 템플릿 대신 웹훅을 렌더해도 모른다
    monkeypatch.setattr(install, "WEBHOOK_FILE", hook)

    def gh(*args, input=None, check=True):
        calls.append((args, input))
        if args[:2] == ("api", "repos/sym804/x"):
            return json.dumps({"default_branch": "main"})
        if "git/trees" in args[1]:
            return json.dumps({"tree": [{"type": "blob", "path": "RELEASE_NOTES.md"}], "truncated": False})
        return ""

    monkeypatch.setattr(install, "gh", gh)
    monkeypatch.setattr(install, "current_workflow", lambda r, b: (old_workflow, "sha1") if old_workflow else (None, None))
    return calls


def _puts(calls):
    return [json.loads(inp) for args, inp in calls if "-X" in args]


def _secrets(calls):
    return [inp for args, inp in calls if args[:2] == ("secret", "set")]


FOREIGN = "name: someone-else" + chr(10)


def test_표지가_없는_같은_이름_워크플로는_덮어쓰지_않는다(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, FOREIGN, tmp_path)
    monkeypatch.setattr(sys, "argv", ["install.py", "--apply", "--repo", "x"])
    assert install.main() == 0
    assert _secrets(calls) == [] and _puts(calls) == []


def test_force_면_덮어쓴다(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, FOREIGN, tmp_path)
    monkeypatch.setattr(sys, "argv", ["install.py", "--apply", "--force", "--repo", "x"])
    assert install.main() == 0
    assert len(_puts(calls)) == 1 and _puts(calls)[0]["sha"] == "sha1"


def test_새_레포에는_비밀값과_워크플로를_넣고_웹훅은_파일에_넣지_않는다(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, None, tmp_path)
    monkeypatch.setattr(sys, "argv", ["install.py", "--apply", "--repo", "x"])
    assert install.main() == 0
    assert _secrets(calls) == [WEBHOOK]
    [put] = _puts(calls)
    content = base64.b64decode(put["content"]).decode("utf-8")
    assert install.MARKER in content and "RELEASE_NOTES.md" in content
    assert "hooks.slack.com" not in content   # 비밀값이 레포 파일로 새면 안 된다
    assert put["branch"] == "main" and "sha" not in put


def test_secrets_only_는_워크플로를_건드리지_않는다(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, None, tmp_path)
    monkeypatch.setattr(sys, "argv", ["install.py", "--apply", "--secrets-only", "--repo", "x"])
    assert install.main() == 0
    assert _secrets(calls) == [WEBHOOK] and _puts(calls) == []
