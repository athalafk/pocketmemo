"""deploy.sh must only deploy full SHAs that are on origin/main."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None or os.name == "nt",
    reason="deploy.sh needs bash and git on a POSIX server",
)


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def server(tmp_path):
    """A server checkout cloned from a local origin, with docker stubbed out."""
    origin = tmp_path / "origin"
    _git(tmp_path, "init", "-q", "-b", "main", str(origin))
    _git(origin, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "one")
    checkout = tmp_path / "server"
    _git(tmp_path, "clone", "-q", str(origin), str(checkout))
    shutil.copy(ROOT / "deploy.sh", checkout / "deploy.sh")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    (bin_dir / "docker").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n')
    (bin_dir / "docker").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env.pop("SSH_ORIGINAL_COMMAND", None)
    return origin, checkout, env, log


def _deploy(checkout, env, sha):
    return subprocess.run(
        ["bash", str(checkout / "deploy.sh")],
        cwd=checkout,
        env={**env, "SSH_ORIGINAL_COMMAND": sha},
        capture_output=True,
        text=True,
    )


def test_deploys_new_main_commit(server):
    origin, checkout, env, log = server
    _git(origin, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "two")
    sha = _git(origin, "rev-parse", "HEAD")

    result = _deploy(checkout, env, sha)

    assert result.returncode == 0, result.stderr
    assert _git(checkout, "rev-parse", "HEAD") == sha
    assert log.read_text().splitlines() == [
        "compose up -d --build",
        "compose exec -T bot alembic upgrade head",
    ]


@pytest.mark.parametrize("sha", ["", "main", "abc123", "0" * 40 + "; rm -rf /"])
def test_rejects_anything_but_a_full_sha(server, sha):
    _, checkout, env, log = server

    assert _deploy(checkout, env, sha).returncode == 2
    assert not log.exists()


def test_rejects_commit_not_on_main(server):
    origin, checkout, env, log = server
    _git(origin, "checkout", "-q", "-b", "feature")
    _git(origin, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "side")
    sha = _git(origin, "rev-parse", "HEAD")
    _git(origin, "checkout", "-q", "main")
    _git(checkout, "fetch", "-q", "origin", "feature")

    result = _deploy(checkout, env, sha)

    assert result.returncode == 1
    assert "not on origin/main" in result.stderr
    assert not log.exists()
