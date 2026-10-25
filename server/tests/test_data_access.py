"""Focused checks for the new access seam; run with the final backend test batch."""
from __future__ import annotations

import re

import pytest
from sqlalchemy import event

from server.app.files import LocalFileStorage
from server.app.state import dev_users
from server.app.storage import SqlMetadataStorage


def test_sql_access_is_scoped_and_paginated(tmp_path):
    storage = SqlMetadataStorage(f'sqlite+pysqlite:///{(tmp_path / "data.sqlite3").as_posix()}')
    storage.initialize()
    users = dev_users()[:2]
    with storage.transaction() as data:
        for user in users:
            data.add_user(user)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(storage._engine, 'before_cursor_execute', capture)
    try:
        with storage.transaction(write=False) as data:
            assert data.find_user(users[0]['username'])['user_id'] == users[0]['user_id']
            assert not hasattr(data, 'users')  # Whole-store access is not part of the seam.
            first, second = data.list_users(1, 1), data.list_users(2, 1)
            assert first.total == second.total == 2
            assert len(first.items) == len(second.items) == 1
            assert first.items[0]['user_id'] != second.items[0]['user_id']
        assert any('LIMIT' in sql.upper() for sql in statements)
        assert not any(re.search(r'\bFROM\s+(samples|images|export_items|sessions)\b', sql, re.I)
                       for sql in statements)
    finally:
        event.remove(storage._engine, 'before_cursor_execute', capture)
        storage.close()


def test_staged_files_publish_immutably_and_cleanup_on_failure(tmp_path):
    files = LocalFileStorage(tmp_path)
    with files.stage() as staged:
        staged.stream.write(b'complete-image')
        assert not files.exists('originals/image.jpg')
        assert staged.publish('originals/image.jpg')
    assert not files.write('originals/image.jpg', b'replacement')
    with files.open_read('originals/image.jpg') as source:
        assert source.read() == b'complete-image'
    with pytest.raises(RuntimeError, match='interrupted'):
        with files.stage() as staged:
            staged.stream.write(b'partial')
            raise RuntimeError('interrupted')
    assert list((tmp_path / 'tmp').iterdir()) == []