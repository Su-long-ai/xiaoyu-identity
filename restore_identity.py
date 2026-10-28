# -*- coding: utf-8 -*-
"""Restore a portable companion identity into a NEW directory. No overwrites."""
from pathlib import Path
import argparse
from identity_core import IdentityStore

def main():
    parser=argparse.ArgumentParser(
        description="Restore XiaoYu identity in a new folder; never overwrite existing identity."
    )
    parser.add_argument("archive",type=Path,help="Portable identity .zip archive")
    parser.add_argument("new_folder",type=Path,help="New nonexistent directory")
    args=parser.parse_args()
    root=IdentityStore.import_to_new_home(args.archive,args.new_folder)
    s=IdentityStore(root)
    try:
        progress=s.actual_progress()
        print("RESTORE_OK")
        print("IDENTITY_ID="+s.persona()["id"])
        print("SCHEMA_VERSION="+str(s._get("schema_version")))
        print("USER_MESSAGES="+str(progress["user_messages"]))
        print("CONFIRMED_MEMORIES="+str(progress["confirmed_memories"]))
        print("PENDING_CANDIDATES="+str(progress["pending_candidates"]))
        print("DIRECTORY="+str(root))
        print("NOTE: Archive contains identity only. To open UI copy the runtime source separately.")
    finally:
        s.close()

if __name__=="__main__":
    main()
