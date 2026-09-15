"""Data-preserving upgrades for private-chat destinations and lifetime.

Run on application startup before requests are served. SQLite rebuilds only the
sessions table inside one write transaction, preserving rows, indexes, triggers,
and dependent records. Existing live application processes should be stopped
before upgrading, as with other schema changes.
"""
import re
from sqlalchemy import inspect, text


def allow_unscoped_private_chats(engine):
    nullable_columns = {"write_domain_id": "VARCHAR", "expires_at": "FLOAT"}
    if engine.dialect.name == 'postgresql':
        with engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock(76823917)'))
            for column in inspect(c).get_columns('sessions'):
                if column['name'] in nullable_columns and not column['nullable']:
                    c.execute(text(f"ALTER TABLE sessions ALTER COLUMN {column['name']} DROP NOT NULL"))
            c.execute(text("UPDATE sessions SET expires_at = NULL WHERE mode = 'private' AND expires_at IS NOT NULL"))
        return
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=OFF')
        cursor.execute('BEGIN IMMEDIATE')
        columns = cursor.execute('PRAGMA table_info(sessions)').fetchall()
        required = [row[1] for row in columns if row[1] in nullable_columns and row[3]]
        if not required:
            cursor.execute("UPDATE sessions SET expires_at = NULL WHERE mode = 'private' AND expires_at IS NOT NULL")
            connection.commit()
            return
        original = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone()[0]
        upgraded = original
        for name in required:
            upgraded, count = re.subn(rf'(\b{name}\s+{nullable_columns[name]})\s+NOT NULL', r'\1', upgraded, count=1, flags=re.I)
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
        cursor.execute("UPDATE sessions SET expires_at = NULL WHERE mode = 'private' AND expires_at IS NOT NULL")
        if cursor.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key validation failed; migration rolled back')
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.close()


def add_finding_details(engine):
    """Add nullable action metadata without rebuilding existing reviewed findings."""
    with engine.begin() as c:
        if engine.dialect.name == 'postgresql':
            c.execute(text('SELECT pg_advisory_xact_lock(76823917)'))
        if 'details' not in {v['name'] for v in inspect(c).get_columns('meeting_findings')}:
            c.execute(text("ALTER TABLE meeting_findings ADD COLUMN details JSON NOT NULL DEFAULT '{}'"))
            # The former extractor only processed decisions; replay saved text for the new types.
            if inspect(c).has_table('meeting_finding_progress'):
                c.execute(text("UPDATE meeting_finding_progress SET processed = '{}', phase = 'idle', error = ''"))
