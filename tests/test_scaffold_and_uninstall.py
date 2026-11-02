"""
Tests for the files `scribe new` writes, and for `scribe uninstall`.
"""

import os
import shutil
import subprocess

import pytest
from click.testing import CliRunner

from scribe.cli import cli
from scribe.scaffold import create_project


@pytest.mark.skipif(shutil.which('git') is None, reason="git not installed")
@pytest.mark.parametrize('demo', [False, True])
def test_gitignore_ignores_secrets_venv_and_build_output(tmp_path, demo):
    project = tmp_path / 'myapp'
    create_project(str(project), 'myapp', demo=demo)
    subprocess.run(['git', 'init', '-q'], cwd=project, check=True)

    paths = ['scribe.json', 'app.db', '.venv/bin/python', 'dist/myapp', '_scribe_build/routes.json']
    result = subprocess.run(['git', 'check-ignore', *paths], cwd=project,
                            capture_output=True, text=True)
    assert result.stdout.split() == paths

    kept = subprocess.run(['git', 'check-ignore', 'app.stpl', 'base.stpl'], cwd=project,
                          capture_output=True, text=True)
    assert kept.stdout == ''


def fake_install(bin_dir, names):
    bin_dir.mkdir(exist_ok=True)
    for name in names:
        path = bin_dir / name
        path.write_text('#!/bin/sh\n')
        path.chmod(0o755)


def run_uninstall(monkeypatch, bin_dir):
    monkeypatch.setenv('PATH', str(bin_dir))
    return CliRunner().invoke(cli, ['uninstall', '-y'])


def test_uninstall_removes_scribe_and_scribe_build(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'bin'
    fake_install(bin_dir, ['scribe', 'scribe-build'])

    result = run_uninstall(monkeypatch, bin_dir)

    assert result.exit_code == 0
    assert os.listdir(bin_dir) == []
    assert 'Successfully uninstalled' in result.output
    assert str(bin_dir / 'scribe-build') in result.output


def test_uninstall_without_scribe_build(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'bin'
    fake_install(bin_dir, ['scribe'])

    result = run_uninstall(monkeypatch, bin_dir)

    assert result.exit_code == 0
    assert os.listdir(bin_dir) == []
    assert 'Successfully uninstalled' in result.output
