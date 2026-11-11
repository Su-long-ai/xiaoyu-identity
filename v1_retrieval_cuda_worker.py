# -*- coding: utf-8 -*-
"""Persistent CUDA worker for the exact frozen V1 retrieval component."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

WINNER_SHA="70b5a1af7d5fe664f563bd3fc05099394b1852a962ee8916ce7f9cad4ab033be"
WINNER_ID="novel_identity_path_v18_possessive"
IMPLEMENTATION_ID=(
    "bge-small-en-v1.5:5c38ec7c405ec4b44b94cc5a9bb96e735b38267a:"
    "torch-cuda-autocast-fp16-v1"
)

def send(obj):
    sys.stdout.write(json.dumps(obj,ensure_ascii=False,separators=(",",":"))+"\n")
    sys.stdout.flush()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    args=ap.parse_args()
    root=Path(args.root).resolve()
    sys.path.insert(0,str(root))
    os.environ["XIAOYU_BGE_BACKEND"]="cuda"
    os.environ.setdefault("HF_HUB_OFFLINE","1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE","1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS","1")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS","1")

    try:
        from research_components.retrieval import api as retrieval_api
        component_path=root/"retrieval_component_v18.py"
        got=hashlib.sha256(component_path.read_bytes()).hexdigest()
        if got!=WINNER_SHA:
            raise RuntimeError("winner_hash_mismatch:"+got)
        component,module_path=retrieval_api.load_component(str(component_path))
        if str(component.component_id)!=WINNER_ID:
            raise RuntimeError("winner_component_id_mismatch")
        info=component.model.backend_info()
        if (
            str(info.get("backend"))!="torch_cuda"
            or str(info.get("requested_backend"))!="cuda"
            or str(info.get("implementation_id"))!=IMPLEMENTATION_ID
        ):
            raise RuntimeError("audited_backend_mismatch:"+repr(info))
        send({
            "status":"READY",
            "component_id":component.component_id,
            "component_sha256":got,
            "backend_info":info,
            "python":sys.executable,
        })
    except Exception as exc:
        send({"status":"ERROR","error":type(exc).__name__+": "+str(exc)})
        raise SystemExit(2)

    documents=[]
    authorized_index={}
    state=None
    for line in sys.stdin:
        try:
            req=json.loads(line)
            cmd=str(req.get("cmd") or "")
            if cmd=="close":
                send({"status":"BYE"})
                return
            if cmd=="prepare":
                documents=[dict(x) for x in req.get("documents",[])]
                authorized_index=retrieval_api.authorized_document_index(documents)
                state=retrieval_api.prepare_component(component,documents)
                send({"status":"OK","prepared":len(documents)})
                continue
            if cmd=="rank":
                if state is None:
                    raise RuntimeError("rank_before_prepare")
                hits=retrieval_api.rank_component(
                    component,state,documents,str(req.get("query") or ""),
                    limit=int(req.get("limit") or 7),
                    authorized_index=authorized_index,
                )
                send({"status":"OK","ids":[str(x["id"]) for x in hits]})
                continue
            raise RuntimeError("unknown_command:"+cmd)
        except Exception as exc:
            send({"status":"ERROR","error":type(exc).__name__+": "+str(exc)})

if __name__=="__main__":
    main()
