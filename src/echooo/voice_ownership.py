"""Keep provider-managed voice resources in their owner's workspace."""
from sqlalchemy import select

from echooo import database as db


def visible_voices(store, who, voices):
    # Trusted resource-ownership lookup: return no other owner's records.
    # Voices predating this registry belong to the original workspace.
    with store.engine.connect() as c:
        original = c.execute(select(db.users.c.id).order_by(
            db.users.c.created_at, db.users.c.id).limit(1)).scalar()
        owners = dict(c.execute(select(db.custom_voices.c.voice_id,
            db.custom_voices.c.owner_id)).all())
    return [v for v in voices if owners.get(v['id'], original) == who]


def register_voice(store, who, voice_id):
    with store.scope(who) as r:
        r.add(db.custom_voices, voice_id=voice_id)
