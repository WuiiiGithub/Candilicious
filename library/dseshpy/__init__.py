"""
Deshpy
===
This package is made for handling discord study sessions
---
Package under development. ^.^

---
Thank you
"""
from pymongo.collection import Collection as _Collection

collections = {}

from . import session

def initialize(
    session_collection: _Collection,
    user_collection: _Collection = None,
    exception_collection: _Collection = None,
    drops_collection: _Collection = None,
    activity_session_collection: _Collection = None
):
    collections['session'] = session_collection
    if user_collection is not None:
        collections['user'] = user_collection
    if exception_collection is not None:
        collections['exception'] = exception_collection
    if drops_collection is not None:
        collections['drop.offers'] = drops_collection
    if activity_session_collection is not None:
        collections['session.logs'] = activity_session_collection