"""Tests for install.py: soft-linking built personas into AI tool directories."""

import pytest

import install


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fake repo with two built personas and one unbuilt one."""
    personas = tmp_path / "repo" / "personas"
    for name, built in [("pip", True), ("quill", True), ("raw", False)]:
        (personas / name).mkdir(parents=True)
        (personas / name / "character.md").write_text("x")
        if built:
            (personas / name / f"{name}.md").write_text(f"{name} persona")
    monkeypatch.setattr(install, "PERSONAS", personas)
    return personas


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


def test_find_persona_files_splits_built_and_unbuilt(repo):
    found, unbuilt = install.find_persona_files()
    assert [p.name for p in found] == ["pip.md", "quill.md"]
    assert unbuilt == ["raw"]


def test_detect_tool_dirs_only_returns_existing_dirs(home):
    (home / ".claude").mkdir()
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".gemini").write_text("a file, not a dir")

    assert install.detect_tool_dirs(home) == [
        home / ".claude" / "personas",
        home / ".config" / "opencode" / "personas",
    ]


def test_default_run_links_into_detected_dirs(repo, home, capsys):
    (home / ".claude").mkdir()

    assert install.main([], home=home) == 0

    link = home / ".claude" / "personas" / "pip.md"
    assert link.is_symlink()
    assert link.resolve() == (repo / "pip" / "pip.md").resolve()
    assert (home / ".claude" / "personas" / "quill.md").is_symlink()
    assert not (home / ".claude" / "personas" / "raw.md").exists()
    assert "not built" in capsys.readouterr().out


def test_undetected_tool_dirs_are_not_created(repo, home):
    (home / ".claude").mkdir()

    install.main([], home=home)

    assert not (home / ".codex").exists()


def test_no_tool_dirs_found(repo, home, capsys):
    assert install.main([], home=home) == 1
    assert "Use --dir" in capsys.readouterr().out


def test_dir_flag_links_directly_and_skips_detection(repo, home, tmp_path):
    (home / ".claude").mkdir()
    target = tmp_path / "custom" / "here"

    assert install.main(["--dir", str(target)], home=home) == 0

    assert (target / "pip.md").is_symlink()
    assert not (home / ".claude" / "personas").exists()


def test_dir_flag_is_repeatable(repo, home, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"

    install.main(["--dir", str(a), "--dir", str(b)], home=home)

    assert (a / "pip.md").is_symlink()
    assert (b / "pip.md").is_symlink()


def test_rerun_is_idempotent(repo, home, tmp_path, capsys):
    args = ["--dir", str(tmp_path / "out")]
    install.main(args, home=home)
    capsys.readouterr()

    assert install.main(args, home=home) == 0
    assert "ok" in capsys.readouterr().out


def test_existing_file_is_not_overwritten_without_force(repo, home, tmp_path, capsys):
    target = tmp_path / "out"
    target.mkdir()
    (target / "pip.md").write_text("my own copy")

    assert install.main(["--dir", str(target)], home=home) == 1

    assert not (target / "pip.md").is_symlink()
    assert (target / "pip.md").read_text() == "my own copy"
    assert "--force" in capsys.readouterr().out
    # The other persona is still linked despite the conflict.
    assert (target / "quill.md").is_symlink()


def test_force_replaces_files_and_stale_links(repo, home, tmp_path):
    target = tmp_path / "out"
    target.mkdir()
    (target / "pip.md").write_text("my own copy")
    (target / "quill.md").symlink_to(tmp_path / "gone.md")  # broken link

    assert install.main(["--dir", str(target), "--force"], home=home) == 0

    assert (target / "pip.md").resolve() == (repo / "pip" / "pip.md").resolve()
    assert (target / "quill.md").resolve() == (repo / "quill" / "quill.md").resolve()


def test_force_never_deletes_a_real_directory(repo, home, tmp_path):
    target = tmp_path / "out"
    (target / "pip.md").mkdir(parents=True)

    assert install.main(["--dir", str(target), "--force"], home=home) == 1

    assert (target / "pip.md").is_dir()


def test_dry_run_changes_nothing(repo, home, tmp_path, capsys):
    target = tmp_path / "out"

    assert install.main(["--dir", str(target), "--dry-run"], home=home) == 0

    assert not target.exists()
    assert "[dry run]" in capsys.readouterr().out


def test_no_built_personas(tmp_path, home, monkeypatch, capsys):
    monkeypatch.setattr(install, "PERSONAS", tmp_path / "empty")

    assert install.main(["--dir", str(tmp_path / "out")], home=home) == 1
    assert "build.py" in capsys.readouterr().out


def test_dry_run_reports_a_file_where_the_dest_dir_should_be(
    repo, home, tmp_path, capsys
):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file")

    # Both the dir itself and a missing dir beneath the file are blocked.
    for target in (blocker, blocker / "sub"):
        assert install.main(["--dir", str(target), "--dry-run"], home=home) == 1

    out = capsys.readouterr().out
    assert "failed" in out
    assert "linked" not in out
    assert blocker.read_text() == "i am a file"


def test_dry_run_matches_real_run_exit_status(repo, home, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file")

    dry = install.main(["--dir", str(blocker), "--dry-run"], home=home)
    real = install.main(["--dir", str(blocker)], home=home)

    assert dry == real == 1
