# -*- coding:utf-8 -*-
"""Read SHA-frozen raw final answers from EXISTING product receipt formats.

Read-only. A completed inference is proven only if each actual provider
finish_reason exists and is a normal terminal status; old receipts remain
diagnostic-only when that metadata was never collected.
"""
from __future__ import annotations

import json
from pathlib import Path
import hashlib


def _read(bundle, name):
    path=Path(bundle[name+"_path"]).resolve()
    if not path.is_file():
        raise ValueError("answer_file_missing:"+name)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=bundle.get(name+"_sha256"):
        raise ValueError("answer_sha_drift:"+name)
    return json.loads(path.read_text("utf8"))


def _indexed(rows, id_key):
    index={x[id_key]:x for x in rows}
    if len(index)!=len(rows):
        raise ValueError("duplicate_answer_ids")
    return index


def _extract(record, names=("answer","final_answer","response")):
    if not isinstance(record,dict):raise ValueError("invalid_output_record")
    value=next((record[k] for k in names if isinstance(record.get(k),str)),None)
    usage=record.get("usage") or {}
    if not isinstance(usage,dict):
        usage={}
    reason=record.get("finish_reason",usage.get("_finish_reason"))
    return {"text":value, "finish_reason":reason,
            "question":str(record.get("question") or "")}


def collect(bundle, rows):
    """Return {case_id:{baseline:{text,finish_reason},candidate:...}}.

    None means unsupported receipt kind; adapter can be added without rewriting
    research or changing historical answers. Any failure is propagated and
    interpreted as integrity unverified, NOT as a false model answer.
    """
    if not isinstance(bundle,dict):
        return None
    kind=bundle.get("kind")
    ids={x["id"] for x in rows}
    if len(ids)!=len(rows):
        raise ValueError("duplicate_case_ids")

    if kind=="public24_real_product_answers_v1":
        source=_read(bundle,"answers")
        answers=source["predictions"]
        base=bundle.get("baseline_arm") or "G26"
        candidate=bundle.get("candidate_arm") or "G27"
        index={(x["id"],x["arm"]):x for x in answers}
        if len(index)!=len(answers) or len(answers)!=2*len(ids):
            raise ValueError("duplicate_or_missing_answers")
        return {ident:{"baseline":_extract(index[(ident,base)],("response",)),
                       "candidate":_extract(index[(ident,candidate)],("response",))}
                for ident in ids}

    if kind=="locomo200_synthetic_real_answers_v1":
        baseline=_read(bundle,"baseline_answers")
        candidate=_read(bundle,"candidate_answers")
        a=_indexed(baseline["rows"],"blind_id")
        b=_indexed(candidate["rows"],"blind_id")
        if set(a)!=ids or set(b)!=ids:raise ValueError("paired_ids_mismatch")
        return {ident:{"baseline":_extract(a[ident]),
                       "candidate":_extract(b[ident])} for ident in ids}

    if kind=="dated_temporal60_real_answers_v1":
        source=_read(bundle,"answers")
        names=(bundle.get("baseline_arm") or "G26",
               bundle.get("candidate_arm") or "G28")
        index={(x["blind_id"],x["arm"]):x for x in source["rows"]}
        if len(index)!=len(source["rows"]) or len(index)!=2*len(ids):
            raise ValueError("paired_ids_mismatch")
        return {ident:{"baseline":_extract(index[(ident,names[0])]),
                       "candidate":_extract(index[(ident,names[1])])}
                for ident in ids}

    if kind=="g71_g69_full200_h_real_paired_v1":
        base0=_read(bundle,"baseline_first_answers")
        base1=_read(bundle,"baseline_second_answers")
        baseline=_indexed(base0["rows"]+base1["rows"],"blind_id")
        if set(baseline)!=ids:
            raise ValueError("baseline_ids_mismatch")
        c={}
        seal=_read(bundle,"candidate_prediction_seal")
        for sid,info in bundle["candidate_sample_answer_paths"].items():
            path=Path(info).resolve()
            # The existing candidate receipt seal binds each sample SHA.
            expected=seal["sample_answer_hashes"][sid]["sha256"]
            if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                raise ValueError("candidate_sample_sha_drift:"+sid)
            data=json.loads(path.read_text("utf8"))
            for x in data["rows"]:
                ident=x["blind_id"]
                if ident in c:raise ValueError("duplicate_sample_id")
                c[ident]=x
        if set(c)!=ids:raise ValueError("candidate_ids_mismatch")
        return {ident:{"baseline":_extract(baseline[ident]),
                       "candidate":_extract(c[ident])} for ident in ids}

    return None
