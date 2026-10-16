"""CI の secret-scan ジョブの検査の step を実際に実行して、検査する範囲を守る回帰テスト。

``ci.yml`` の「Scan for secrets」の ``run`` を取り出し、GitHub の runner と同じ bash のオプションで、
一時ディレクトリの git リポジトリと偽の ``gitleaks`` に対して実行する。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

CI_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
SCAN_STEP_NAME = "- name: Scan for secrets"
# 偽の gitleaks が検出として扱う目印。秘密の形をしない文字列にして、このリポジトリ自身の検査に掛からないようにする
_MARKER = "SECRET-SCAN-TEST-MARKER"
_EVENTS = ("pull_request_target", "push", "workflow_dispatch")

# 偽の gitleaks。Gitleaks 8.30.1 と同じ引数で git log を実際に実行し、追加行（Gitleaks が検査する行）に
# FAKE_GITLEAKS_MARKER があれば検出として 1 で終わる。引数の組み立ては 8.30.1 の --log-level debug の
# 出力に合わせた: --log-opts があれば値を空白で分割して git -C <source> log -p -U0 に渡し、既定の引数を
# 足さない。無ければ --full-history --all --diff-filter=tuxdb を渡す。呼び出しごとに JSON の 1 行を記録する
_FAKE_GITLEAKS = """\
import json
import os
import subprocess
import sys

argv = sys.argv[1:]
log_opts = [arg.removeprefix("--log-opts=") for arg in argv if arg.startswith("--log-opts=")]
opts = log_opts[-1].split(" ") if log_opts else ["--full-history", "--all", "--diff-filter=tuxdb"]
output = subprocess.run(
    ["git", "-C", argv[-1], "log", "-p", "-U0", *opts],
    check=True,
    capture_output=True,
    text=True,
).stdout
marker = os.environ["FAKE_GITLEAKS_MARKER"]
leaks = sum(
    1
    for line in output.splitlines()
    if line.startswith("+") and not line.startswith("+++") and marker in line
)
with open(os.environ["FAKE_GITLEAKS_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": argv, "leaks": leaks}) + "\\n")
sys.exit(1 if leaks else 0)
"""

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="the scan step needs bash and git",
)


@dataclass
class _ScanRepo:
    """検査の step を実行する一時の環境。

    履歴は ``B0 ── B1(main)`` と ``B0 ── P1 ── M(refs/pull/7/head)``。M は P1 に B1 をマージした commit。
    workspace は origin の clone で、B1 を detached で checkout している。
    """

    origin: Path
    workspace: Path
    base_sha: str
    head_sha: str
    bin_dir: Path
    log: Path


def _git_env() -> dict[str, str]:
    """利用者の git の設定（log.diffMerges など）と GIT_* の環境変数を読まない環境。"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
    )
    return env


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, env=_git_env(), check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _scan_step_script() -> str:
    """ci.yml の「Scan for secrets」の step の run を返す。"""
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == SCAN_STEP_NAME]
    assert len(starts) == 1, f"ci.yml に {SCAN_STEP_NAME!r} の step が 1 つだけ無い"
    start = starts[0]
    step_indent = len(lines[start]) - len(lines[start].lstrip())
    run_index = None
    for index in range(start + 1, len(lines)):
        line = lines[index]
        indent = len(line) - len(line.lstrip())
        if line.strip() and indent <= step_indent:
            break
        if line.strip() == "run: |":
            run_index = index
            break
    assert run_index is not None, f"{SCAN_STEP_NAME!r} の step に run: | が無い"
    key_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
    body: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= key_indent:
            break
        body.append(line)
    script = textwrap.dedent("\n".join(body)).strip()
    assert script, f"{SCAN_STEP_NAME!r} の step の run が空"
    return script + "\n"


def _make_scan_repo(
    tmp_path: Path,
    *,
    merge_resolution: str,
    pr_files: dict[str, str] | None = None,
) -> _ScanRepo:
    """main と PR が同じ行を変え、PR に main を取り込むマージ commit で競合を merge_resolution で解消する。"""
    origin = tmp_path / "origin.git"
    src = tmp_path / "src"
    workspace = tmp_path / "workspace"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(src))
    _commit(src, {".gitleaks.toml": "[extend]\nuseDefault = true\n", "settings.txt": "original\n"}, "base")
    _git(src, "checkout", "-q", "-b", "pr")
    _commit(src, {"settings.txt": "pr\n", **(pr_files or {})}, "pr")
    _git(src, "checkout", "-q", "main")
    base_sha = _commit(src, {"settings.txt": "main\n"}, "main")
    _git(src, "checkout", "-q", "pr")
    merge = subprocess.run(
        ["git", "merge", "-q", "--no-commit", "--no-ff", "main"],
        cwd=src,
        env=_git_env(),
        check=False,
        capture_output=True,
        text=True,
    )
    # 競合させること自体が前提。競合しないとマージ commit の差分が空になり、テストの意味が変わる
    assert merge.returncode == 1, merge.stdout + merge.stderr
    head_sha = _commit(src, {"settings.txt": merge_resolution}, "merge main into pr")
    _git(src, "push", "-q", str(origin), "main:refs/heads/main", "pr:refs/pull/7/head")
    # actions/checkout（fetch-depth: 0）と同じく、refs/pull/* は取得しない
    _git(tmp_path, "clone", "-q", str(origin), str(workspace))
    _git(workspace, "checkout", "-q", "--detach", base_sha)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "gitleaks"
    fake.write_text(f"#!{sys.executable}\n{_FAKE_GITLEAKS}", encoding="utf-8")
    fake.chmod(0o755)
    return _ScanRepo(
        origin=origin,
        workspace=workspace,
        base_sha=base_sha,
        head_sha=head_sha,
        bin_dir=bin_dir,
        log=tmp_path / "gitleaks.jsonl",
    )


def _event(repo: _ScanRepo, event_name: str) -> dict[str, str]:
    """イベントの環境変数を返す。push と手動の実行は、PR の head が main に入った後として head を checkout する。"""
    if event_name == "pull_request_target":
        return {
            "EVENT_NAME": event_name,
            "PR_NUMBER": "7",
            "BASE_SHA": repo.base_sha,
            "HEAD_SHA": repo.head_sha,
            "PUSH_BEFORE": "",
            "PUSH_AFTER": repo.base_sha,
        }
    _git(repo.workspace, "fetch", "-q", "origin", "refs/pull/7/head")
    _git(repo.workspace, "checkout", "-q", "--detach", repo.head_sha)
    return {
        "EVENT_NAME": event_name,
        "PR_NUMBER": "",
        "BASE_SHA": "",
        "HEAD_SHA": "",
        # 手動の実行では before が空になり、全履歴を検査する
        "PUSH_BEFORE": repo.base_sha if event_name == "push" else "",
        "PUSH_AFTER": repo.head_sha,
    }


def _run_scan(repo: _ScanRepo, event: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """GitHub の runner と同じ bash のオプションで、workspace を cwd にして検査の step を実行する。"""
    script = repo.workspace.parent / "scan-step.sh"
    script.write_text(_scan_step_script(), encoding="utf-8")
    env = _git_env()
    env.update(
        {
            "PATH": f"{repo.bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_WORKSPACE": str(repo.workspace),
            "FAKE_GITLEAKS_LOG": str(repo.log),
            "FAKE_GITLEAKS_MARKER": _MARKER,
            **event,
        }
    )
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        cwd=repo.workspace,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _scanner_calls(repo: _ScanRepo) -> list[dict[str, object]]:
    if not repo.log.exists():
        return []
    return [json.loads(line) for line in repo.log.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("event_name", _EVENTS)
def test_secret_introduced_by_merge_commit_fails_scan(tmp_path: Path, event_name: str) -> None:
    """競合の解消でだけ入った内容も、PR・push・手動のどの経路でも検出して失敗する。

    git log -p は既定でマージ commit の差分を出さないので、-m が無いとこの内容は scanner に届かない。
    """
    repo = _make_scan_repo(tmp_path, merge_resolution=f"resolved {_MARKER}\n")

    result = _run_scan(repo, _event(repo, event_name))

    [call] = _scanner_calls(repo)
    assert call["leaks"], result.stderr
    assert result.returncode != 0


@pytest.mark.parametrize("event_name", _EVENTS)
def test_merge_commit_without_secret_passes_scan(tmp_path: Path, event_name: str) -> None:
    repo = _make_scan_repo(tmp_path, merge_resolution="resolved\n")

    result = _run_scan(repo, _event(repo, event_name))

    assert result.returncode == 0, result.stderr
    [call] = _scanner_calls(repo)
    assert call["leaks"] == 0


def test_full_history_scan_covers_refs_unreachable_from_head(tmp_path: Path) -> None:
    """手動の実行の全履歴は、HEAD から届かない remote-tracking branch の commit も検査する。"""
    repo = _make_scan_repo(tmp_path, merge_resolution="resolved\n", pr_files={"notes.txt": f"{_MARKER}\n"})
    # 目印の commit は origin/feature からだけ届き、workspace の HEAD（B1）からは届かない
    _git(repo.origin, "update-ref", "refs/heads/feature", repo.head_sha)
    _git(repo.workspace, "fetch", "-q", "origin")
    event = {
        "EVENT_NAME": "workflow_dispatch",
        "PR_NUMBER": "",
        "BASE_SHA": "",
        "HEAD_SHA": "",
        "PUSH_BEFORE": "",
        "PUSH_AFTER": repo.base_sha,
    }

    result = _run_scan(repo, event)

    [call] = _scanner_calls(repo)
    assert call["leaks"], result.stderr
    assert result.returncode != 0
