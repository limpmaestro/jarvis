"""Shell denylist tests."""

from __future__ import annotations

import pytest

from jarvis.tools.shell import _denied


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /",
        "rm -rf / --no-preserve-root",
        "mkfs.ext4 /dev/sda1",
        "mkfs /dev/sdb",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
        "shutdown -h now",
        "reboot",
        "chmod -R 777 /bin",
    ],
)
def test_denied(cmd):
    assert _denied(cmd) is not None


@pytest.mark.parametrize(
    "cmd",
    [
        "ls -la",
        "cat /etc/os-release",
        "python3 --version",
        "rm -rf ./my_temp_dir",
        "echo hello",
    ],
)
def test_allowed(cmd):
    assert _denied(cmd) is None
