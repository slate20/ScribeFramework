"""
Tests for injecting a project's virtualenv, and the Python version check.
"""

import json
import os
import stat
import sys

from scribe.app import inject_project_venv


def fake_venv(project, version, site_packages):
    """A .venv whose bin/python reports the given version and sys.path, like a real venv would."""
    bin_dir = project / '.venv' / 'bin'
    bin_dir.mkdir(parents=True)
    python = bin_dir / 'python'
    payload = json.dumps({"path": [str(site_packages)], "version": list(version)})
    python.write_text(f"#!/bin/sh\necho '{payload}'\n")
    python.chmod(python.stat().st_mode | stat.S_IEXEC)


def test_matching_venv_is_injected_quietly(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.delenv('VIRTUAL_ENV', raising=False)
    site = tmp_path / 'site-packages'
    fake_venv(tmp_path, sys.version_info[:2], site)

    inject_project_venv(str(tmp_path))

    out = capsys.readouterr().out
    assert str(site) in sys.path
    assert "(1 paths injected)" in out
    assert "Warning" not in out


def test_mismatched_venv_is_injected_with_a_warning(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.delenv('VIRTUAL_ENV', raising=False)
    site = tmp_path / 'site-packages'
    fake_venv(tmp_path, (3, 9), site)

    inject_project_venv(str(tmp_path))

    out = capsys.readouterr().out
    running = f"{sys.version_info[0]}.{sys.version_info[1]}"
    # Pure-Python packages still work, so the venv is still added
    assert str(site) in sys.path
    assert f".venv uses Python 3.9, but Scribe runs Python {running}" in out
    assert f"uv venv --python {running} .venv" in out
