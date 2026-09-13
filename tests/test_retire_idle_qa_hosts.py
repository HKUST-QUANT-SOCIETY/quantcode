import json
import sqlite3

import pytest

from scripts import retire_idle_qa_hosts as retire


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(retire, "ROOT", tmp_path / "hosts")
    monkeypatch.setattr(retire, "STATE", tmp_path / "state")
    monkeypatch.setattr(retire, "CGROUP", tmp_path / "cgroups")
    unit = "quantcode-native-sim-agent-260909-e2e-20260909-06.service"
    release = retire.ROOT / "sim-agent-260909/e2e-20260909-06"
    state = retire.STATE / "sim-agent-260909/e2e-20260909-06"
    release.mkdir(parents=True)
    state.mkdir(parents=True)
    (release / "native-host.json").write_text(json.dumps({"unit_name": unit, "paths": {"state": str(state)}}))
    return unit, release, state


def test_retirement_scope_excludes_member_hosts_and_recent_tests(host):
    unit, _, _ = host
    assert retire.inspect(unit, "20260913")["unit"] == unit
    with pytest.raises(ValueError, match="old QA"):
        retire.inspect("quantcode-native-quantadmin-unified-admin-v1.service", "20260913")
    with pytest.raises(ValueError, match="old QA"):
        retire.inspect(unit, "20260909")


def test_retirement_refuses_a_changed_state_path(host, tmp_path):
    unit, release, _ = host
    (release / "native-host.json").write_text(json.dumps({"unit_name": unit, "paths": {"state": str(tmp_path)}}))
    with pytest.raises(ValueError, match="path changed"):
        retire.inspect(unit, "20260913")


def test_retirement_refuses_active_tasks_and_accepts_only_the_latest_idle_event(host):
    unit, _, state = host
    cgroup = retire.CGROUP / unit
    cgroup.mkdir(parents=True)
    (cgroup / "cgroup.procs").write_text("999999999\n")
    (cgroup / "memory.current").write_text("1000")
    with sqlite3.connect(state / "fixture.db") as db:
        db.execute("CREATE TABLE event(aggregate_id TEXT,seq INTEGER,type TEXT,data TEXT)")
        db.execute("INSERT INTO event VALUES('task',1,'quantcode.execution.changed.1',?)", (json.dumps({"status": "busy", "pid": 999999999}),))
    with pytest.raises(ValueError, match="active task"):
        retire.inspect(unit, "20260913")
    with sqlite3.connect(state / "fixture.db") as db:
        db.execute("INSERT INTO event VALUES('task',2,'quantcode.execution.changed.1',?)", (json.dumps({"status": "idle", "pid": 999999999}),))
    assert retire.inspect(unit, "20260913")["memory_bytes"] == 1000
