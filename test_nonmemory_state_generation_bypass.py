# -*- coding: utf-8 -*-
from __future__ import annotations
import tempfile
from pathlib import Path
from identity_core import IdentityStore

with tempfile.TemporaryDirectory() as td:
    s=IdentityStore(Path(td))
    try:
        before_gen=s.memory_generation()
        before=s.identity_context("probe",memories_override=[])
        state=s.state()
        state["mood"]=1 if int(state.get("mood",80))!=1 else 2
        s.set_state(state)
        after_gen=s.memory_generation()
        after=s.identity_context("probe",memories_override=[])
        assert before_gen==after_gen, (before_gen,after_gen)
        assert before!=after
        print("PASS state_changes_context_without_memory_generation")
    finally:
        s.close()
