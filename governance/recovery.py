# -*- coding: utf-8 -*-
"""Crash/turn-cutoff recovery by scanning durable workspace files on demand.

No end-of-turn checkpoint call required. No model calls, background service,
cross-agent workspace reading, or modification of old immutable evidence.
"""
import os
from pathlib import Path

def files_in_workspace(workspace, max_files=20, max_seen=5000):
    root=Path(workspace)
    if not root.is_dir() or root.is_symlink():
        return {"file_count":0,"recent_files":[],"exists":False}
    records=[]
    skipped={"__pycache__", ".git", ".venv", "node_modules", ".pytest_cache"}
    control_files={"REUSE_DECISION.json"}
    visited=0
    truncated=False
    for base, dirs, files in os.walk(root, followlinks=False):
        level=len(Path(base).relative_to(root).parts)
        dirs[:]=[d for d in dirs if d not in skipped and not (Path(base)/d).is_symlink()]
        if level >= 6:
            dirs.clear()
        for name in files:
            if level==0 and name in control_files:
                continue
            visited+=1
            if visited>max_seen:
                truncated=True
                break
            p=Path(base)/name
            try:
                if p.is_symlink() or not p.is_file() or p.suffix==".pyc":
                    continue
                stat=p.stat()
                records.append({"path":p.relative_to(root).as_posix(),
                                "bytes":stat.st_size,"modified_at":stat.st_mtime})
            except (OSError,ValueError):
                continue
        if truncated:
            break
    records.sort(key=lambda d:(-d["modified_at"],d["path"]))
    return {"file_count":len(records),"recent_files":records[:max_files],
            "exists":True,"scan_truncated":truncated}

def recent_unfinished(g,agent_id):
    # Only the most recent lease matters; a later submit supersedes old unfinished work.
    row=g.db.execute("SELECT * FROM leases WHERE agent_id=? "
                     "ORDER BY claimed_at DESC, rowid DESC LIMIT 1",(agent_id,)).fetchone()
    if not row or row["state"] not in ("STALE","TTL_EXPIRED"):
        return None
    # A receipt may exist even though a process was interrupted BEFORE
    # SQLite commit. Never confuse a disk file with a completed submission.
    submitted=g.db.execute("SELECT 1 FROM submissions WHERE lease_id=?",
                           (row["lease_id"],)).fetchone()
    if submitted:
        return None
    return row

def attach_files(response,workspace,recovery_state=None):
    data=dict(response)
    data["workspace_recovery"]=files_in_workspace(workspace)
    data["recovery_note"]="Workspace files were written DURING research, not at turn end; read these source files to reconstruct actual progress. Unsaved thoughts cannot be recovered."
    if recovery_state:
        data["recovery_state"]=recovery_state
    return data
