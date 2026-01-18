import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pactown.user_isolation import IsolatedUser, UserIsolationManager, _sanitize_gecos


def test_sanitize_gecos_removes_colon_and_control_chars() -> None:
    assert ":" not in _sanitize_gecos("user:1")
    assert _sanitize_gecos("user:1").startswith("user_1")
    assert "\n" not in _sanitize_gecos("user\n1")


def test_get_or_create_user_non_root_virtual_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "getgid", lambda: 1000)

    import pwd as pwd_module

    monkeypatch.setattr(pwd_module, "getpwall", lambda: [])

    users_base = tmp_path / "users"
    mgr = UserIsolationManager(users_base=users_base)

    user = mgr.get_or_create_user("user:1")

    assert user.linux_uid == 1000
    assert user.linux_gid == 1000
    assert user.home_dir.exists()
    assert str(user.home_dir).startswith(str(users_base))


def test_get_or_create_user_reuses_existing_linux_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    import pwd as pwd_module

    monkeypatch.setattr(pwd_module, "getpwall", lambda: [])

    users_base = tmp_path / "users"
    mgr = UserIsolationManager(users_base=users_base)

    expected_username = mgr._generate_username("user:1")

    def fake_getpwnam(name: str):
        assert name == expected_username
        return SimpleNamespace(
            pw_name=expected_username,
            pw_uid=60010,
            pw_gid=60010,
            pw_dir=str(tmp_path / "home"),
        )

    monkeypatch.setattr(pwd_module, "getpwnam", fake_getpwnam)

    user = mgr.get_or_create_user("user:1")

    assert user.linux_username == expected_username
    assert user.linux_uid == 60010
    assert user.linux_gid == 60010
    assert user.home_dir == tmp_path / "home"


def test_get_or_create_user_root_creates_user_with_sanitized_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    import pwd as pwd_module

    monkeypatch.setattr(pwd_module, "getpwall", lambda: [])

    def fake_getpwnam(_: str):
        raise KeyError

    monkeypatch.setattr(pwd_module, "getpwnam", fake_getpwnam)

    import grp as grp_module

    def fake_getgrnam(_: str):
        raise KeyError

    monkeypatch.setattr(grp_module, "getgrnam", fake_getgrnam)

    import shutil as shutil_module

    monkeypatch.setattr(shutil_module, "which", lambda _: "/usr/sbin/true")

    calls: list[list[str]] = []

    import subprocess as subprocess_module

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(subprocess_module, "run", fake_run)

    users_base = tmp_path / "users"
    mgr = UserIsolationManager(users_base=users_base)

    user = mgr.get_or_create_user("user:1")

    # groupadd then useradd
    assert any(c and c[0] == "groupadd" for c in calls)
    useradd_calls = [c for c in calls if c and c[0] == "useradd"]
    assert len(useradd_calls) == 1

    useradd_cmd = useradd_calls[0]
    assert "-c" in useradd_cmd
    comment = useradd_cmd[useradd_cmd.index("-c") + 1]
    assert comment == "user_1"

    assert isinstance(user, IsolatedUser)
    assert user.linux_uid == mgr.BASE_UID
    assert user.linux_gid == mgr.BASE_GID


def test_delete_user_root_builds_userdel_cmd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pwd as pwd_module

    monkeypatch.setattr(pwd_module, "getpwall", lambda: [])

    mgr = UserIsolationManager(users_base=tmp_path / "users")

    user = IsolatedUser(
        saas_user_id="user:1",
        linux_username="pactown_testuser",
        linux_uid=60000,
        linux_gid=60000,
        home_dir=tmp_path / "home",
    )
    mgr._users[user.saas_user_id] = user

    monkeypatch.setattr(os, "geteuid", lambda: 0)

    calls: list[list[str]] = []

    import subprocess as subprocess_module

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(subprocess_module, "run", fake_run)

    assert mgr.delete_user("user:1", delete_home=True)

    assert calls[0] == ["userdel", "-r", "pactown_testuser"]
