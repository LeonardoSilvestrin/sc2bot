"""Structures to build: `BUILD_PRODUCTION`, `BUILD_ADDON`, `PRODUCE_SUPPLY`
and `BUILD_GAS`.

`capacity.py` holds the one real assessment here: whether army demand and
producer utilization justify another Barracks, Factory or Starport. Which
SCV lays the structure is not decided in this folder at all -- the economy
adapter's Ares behaviors pick one while executing the funded action.
"""
