from echooo import database as db


def test_all_owner_data_tables_receive_postgres_policies_and_grants():
    # Credentials are managed by authentication, outside the scoped repository.
    scoped = {table for table in db.metadata.tables.values()
        if 'owner_id' in table.c and table is not db.tokens}
    assert set(db.OWNED) == scoped
