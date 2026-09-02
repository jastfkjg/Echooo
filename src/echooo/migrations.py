"""Small, data-preserving upgrade for optional private-chat memory destinations.

Run on application startup before requests are served. SQLite rebuilds only the
sessions table inside one write transaction, preserving rows, indexes, triggers,
and dependent records. Existing live application processes should be stopped
before upgrading, as with other schema changes.
"""
import re
from sqlalchemy import inspect, text


def allow_unscoped_private_chats(engine):
    if engine.dialect.name == 'postgresql':
        with engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock(76823917)'))
            column = next(x for x in inspect(c).get_columns('sessions') if x['name'] == 'write_domain_id')
            if not column['nullable']:
                c.execute(text('ALTER TABLE sessions ALTER COLUMN write_domain_id DROP NOT NULL'))
        return
    with engine.connect() as c:
        if not next(row[3] for row in c.exec_driver_sql('PRAGMA table_info(sessions)') if row[1] == 'write_domain_id'):
            return
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=OFF')
        cursor.execute('BEGIN IMMEDIATE')
        columns = cursor.execute('PRAGMA table_info(sessions)').fetchall()
        if not next(row[3] for row in columns if row[1] == 'write_domain_id'):
            connection.commit()
            return
        original = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone()[0]
        upgraded, count = re.subn(r'(\bwrite_domain_id\s+VARCHAR)\s+NOT NULL', r'\1', original, count=1, flags=re.I)
        if count != 1:
            raise RuntimeError('Unexpected sessions schema; no migration was applied')
        upgraded, count = re.subn(r'^CREATE TABLE\s+["`\[]?sessions["`\]]?', 'CREATE TABLE sessions_global_chat', upgraded, count=1, flags=re.I)
        if count != 1:
            raise RuntimeError('Unexpected sessions table name; no migration was applied')
        objects = cursor.execute("SELECT sql FROM sqlite_master WHERE tbl_name='sessions' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        names = ', '.join('"' + row[1].replace('"', '""') + '"' for row in columns)
        cursor.execute(upgraded)
        cursor.execute(f'INSERT INTO sessions_global_chat ({names}) SELECT {names} FROM sessions')
        cursor.execute('DROP TABLE sessions')
        cursor.execute('ALTER TABLE sessions_global_chat RENAME TO sessions')
        for (sql,) in objects:
            cursor.execute(sql)
        if cursor.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key validation failed; migration rolled back')
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.close()
