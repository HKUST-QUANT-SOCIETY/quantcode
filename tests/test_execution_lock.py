from __future__ import annotations

import pytest

from runner.execution_lock import execution_lock


def test_execution_lock_rejects_overlapping_writer(tmp_path):
    database = tmp_path / "checkpoint.db"
    with execution_lock(database, "same-thread"):
        with pytest.raises(RuntimeError, match="RUN_BUSY"):
            with execution_lock(database, "same-thread"):
                pass


def test_execution_lock_separates_thread_ids(tmp_path):
    database = tmp_path / "checkpoint.db"
    with execution_lock(database, "thread-a"):
        with execution_lock(database, "thread-b"):
            pass
