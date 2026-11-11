#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R52 offline composition candidate.

Scientific boundary:
- exact frozen R47 store + accepted R49 structural-v5/atomic confirmation;
- zero provider calls;
- public paid-canary cases are structural-only and reuse existing receipts;
- synthetic projector is a deterministic composition fixture, NOT model-quality evidence;
- destructive mutations are never auto-confirmed inside the pipeline.
"""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from typing import Any

from r47_open_domain_memory_store_frozen import OpenDomainMemoryStore, source_message_id
import r49_structural_v5 as structural
from r49_atomic_confirmed_transition import R49AtomicConfirmedSemanticTransition
from r49_confirmed_transition import canonical_candidates
from r52_qa_sufficiency_v7 import select_supported

HERE=Path(__file__).resolve().parent
GOV=HERE.parents[1]
CANARY_RUNTIME=GOV/"e2_r49_canary_runtime"

def stable(x:Any)->str:
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def norm_tokens(s:str)->set[str]:
    xs=re.findall(r"[a-z0-9]+",str(s).casefold())
    stop={"i","my","me","you","your","the","a","an","is","are","was","were","to","of","in","on","at",
          "for","with","and","or","it","that","this","as","did","do","does","what","which","who",
          "please","could","would","current","actually","establish","established","retrieve","evidence"}
    out=set()
    for x in xs:
        if len(x)>4 and x.endswith("ing"): x=x[:-3]
        elif len(x)>3 and x.endswith("ed"): x=x[:-2]
        elif len(x)>3 and x.endswith("s"): x=x[:-1]
        if x.isdigit(): continue
        if len(x)>1 and x not in stop: out.add(x)
    return out

def lexical_score(query:str,text:str)->tuple[int,float]:
    q=norm_tokens(query);t=norm_tokens(text)
    if not q or not t:return (0,0.0)
    inter=len(q&t)
    return inter, inter/max(1,len(q))

class R52Composition:
    def __init__(self,db_path,identity_id="r52-test-identity",
                 confirmation_key=b"r52-offline-confirmation-key-v1"):
        self.store=OpenDomainMemoryStore(db_path)
        self.transition=R49AtomicConfirmedSemanticTransition(
            self.store,identity_id=identity_id,confirmation_key=confirmation_key)
        self.identity_id=identity_id
        # Caller-owned external IDs never enter model output. This map is reconstructible
        # from the trusted input envelope on restart.
        self.external_by_internal={}
        self.seen_external={}
        self.pending=[]
        self.mutations=0

    def close(self):self.store.close()

    def _bind_source(self,src):
        internal=source_message_id(src["conversation_id"],src["message_id"])
        external=str(src["source_id"])
        old=self.external_by_internal.get(internal)
        if old is not None and old!=external:
            raise ValueError("external_source_binding_drift")
        self.external_by_internal[internal]=external
        self.seen_external[external]={
            "source_id":external,
            "source_role":src["source_role"],
            "effective_at":int(src["effective_at"])
        }
        return internal

    def ingest_source_envelope_only(self,src):
        """Persist trusted full-dialogue source identity/role/time without semantic projection."""
        self._bind_source(src)
        return self.store.ingest(
            src["conversation_id"],src["message_id"],src["message_seq"],src["source_role"],
            src["text"],src["effective_at"],[])

    def _prior(self,src):
        meta=structural.prior_candidates_from_r47(
            self.store,src["text"],src["source_role"],int(src["effective_at"]),
            limit=6,return_metadata=True)
        return meta["candidates"],bool(meta["discovery_complete"])

    @staticmethod
    def _fixture_projection(src,built):
        """Generic deterministic synthetic fixture projector.

        It does not inspect case IDs, family labels, questions, gold, or benchmark
        metadata. It only consumes trusted source text plus caller binding.
        """
        bind=built["caller_binding"][0]
        text=str(src["text"])
        role=str(src["source_role"])
        pmode=bind["projection_mode"]
        bmode=bind["binding_mode"]
        if pmode=="raw_history_only":
            return {"outputs":[{"status":"no_memory","proposals":[]}]}
        if bmode in ("ambiguous","missing"):
            return {"outputs":[{"status":"ambiguous","proposals":[]}]}

        low=text.casefold()
        # Explicit destructive source language. Authorization still comes solely
        # from caller-owned target_components and frozen validator.
        destructive = any(k in low for k in (
            "correction:"," replace ","no longer","forget that","retract ","withdraw ",
            "switched ","changed ","moved from ","update my ","don't want it anymore"
        ))
        comps=bind.get("target_components") or []
        if destructive:
            if len(comps)!=1:
                return {"outputs":[{"status":"ambiguous","proposals":[]}]}
            if "forget" in low or "retract" in low or "withdraw" in low or "don't want it anymore" in low:
                rel="RETRACT"
            elif "disagree" in low or "conflict" in low:
                rel="CONFLICT"
            else:
                rel="SUPERSEDE"
            return {"outputs":[{"status":"propose","proposals":[{
                "claim_text":text.strip(),"evidence_quote":text,
                "relation":rel,"target_ids":list(comps[0])
            }]}]}

        # Durable user assertion. Questions/requests alone are not durable user state.
        if role=="user":
            stripped=text.strip()
            if stripped.endswith("?") or re.match(r"^(could|would|can|please|which|what|who|where|when|how)\b",low):
                return {"outputs":[{"status":"no_memory","proposals":[]}]}
            return {"outputs":[{"status":"propose","proposals":[{
                "claim_text":stripped,"evidence_quote":text,
                "relation":"NEW","target_ids":[]
            }]}]}
        return {"outputs":[{"status":"no_memory","proposals":[]}]}

    def ingest_source(self,src,raw_projection=None):
        self._bind_source(src)
        pri,complete=self._prior(src)
        built=structural.build_model_payload([{
            "source_text":src["text"],"source_role":src["source_role"],
            "prior_candidates":pri,"candidate_pool_complete":complete
        }],limit=6)
        raw=raw_projection if raw_projection is not None else self._fixture_projection(src,built)

        # Always validate through the exact accepted R49 structural-v5 boundary.
        canonical=structural.validate_response(raw,built["model_payload"],built["caller_binding"])
        destructive=any(
            p["relation"] in ("SUPERSEDE","RETRACT","CONFLICT")
            for item in canonical["outputs"] for p in (item.get("proposals") or [])
        )
        if destructive:
            before=stable(self.store.current_view())
            proposal=self.transition.propose(
                raw,built["model_payload"],built["caller_binding"],
                conversation_id=src["conversation_id"],message_id=src["message_id"],
                message_seq=src["message_seq"],source_role=src["source_role"],
                source_text=src["text"],effective_at=src["effective_at"])
            after=stable(self.store.current_view())
            if before!=after:
                raise AssertionError("unconfirmed_destructive_mutated_state")
            rec={
                "relation":next(p["relation"] for x in canonical["outputs"] for p in x["proposals"]),
                "binding_mode":built["caller_binding"][0]["binding_mode"],
                "confirmable":proposal.get("status")=="pending",
                "status":proposal.get("status"),
                "action_id":proposal.get("action_id"),
                "source_id":src["source_id"]
            }
            self.pending.append(rec)
            return {"kind":"pending","pending":rec,"canonical":canonical}

        # NEW/no-memory uses the same frozen R47 source boundary. A no-memory source
        # is still persisted with [] claims, preserving full dialogue provenance.
        candidates=canonical_candidates(canonical)
        rr=self.store.ingest(
            src["conversation_id"],src["message_id"],src["message_seq"],src["source_role"],
            src["text"],src["effective_at"],candidates)
        return {"kind":"ingested","ingest":rr,"canonical":canonical}

    def probe_unbound_destructive(self,src,prior_text,relation="SUPERSEDE"):
        """Attempt a caller-unbound destructive transition and require fail-closed.

        This is driven only by caller-provided prior text in the holdout input.
        The prior candidate is not materialized into authoritative R47 state.
        """
        self._bind_source(src)
        prior=[{"id":"caller-prior:"+stable(prior_text)[:24],"text":str(prior_text),
                "source_role":src["source_role"],
                "authority":"user_state" if src["source_role"]=="user" else "conversation_history",
                "status":"active","effective_at":int(src["effective_at"])-1}]
        built=structural.build_model_payload([{
            "source_text":src["text"],"source_role":src["source_role"],
            "prior_candidates":prior,"candidate_pool_complete":True
        }],limit=6)
        bind=built["caller_binding"][0]
        raw={"outputs":[{"status":"propose","proposals":[{
            "claim_text":str(src["text"]).strip(),"evidence_quote":src["text"],
            "relation":relation,"target_ids":[prior[0]["id"]]
        }]}]}
        rejected=False;err=None
        try:
            structural.validate_response(raw,built["model_payload"],built["caller_binding"])
        except Exception as e:
            rejected=True;err=type(e).__name__+":"+str(e)
        if not rejected:
            raise AssertionError("known_unbound_destructive_became_valid")
        # Preserve trusted source envelope, zero semantic mutation.
        rr=self.store.ingest(
            src["conversation_id"],src["message_id"],src["message_seq"],src["source_role"],
            src["text"],src["effective_at"],[])
        rec={"relation":relation,"binding_mode":bind["binding_mode"],
             "confirmable":False,"status":"blocked","error":err,"source_id":src["source_id"]}
        self.pending.append(rec)
        return rec,rr

    def confirm(self,action_id):
        before=stable(self.store.current_view())
        r=self.transition.confirm(action_id,self.identity_id)
        after=stable(self.store.current_view())
        if before!=after:self.mutations+=1
        return r

    def _external_sid(self,internal):
        return self.external_by_internal.get(str(internal),str(internal))

    def current_rows(self):
        v=self.store.current_view()
        out=[]
        for x in v["current"]:
            out.append({"text":x["claim_text"],"authority":"user_state",
                        "source_id":self._external_sid(x["source_message_id"])})
        for x in v["conflict"]:
            out.append({"text":x["claim_text"],"authority":"user_conflict",
                        "source_id":self._external_sid(x["source_message_id"])})
        return out

    def history_rows(self):
        out=[]
        conflicted=self.store._conflicted_user_claims()
        for x in self.store.history():
            if x["status"]=="quarantined":continue
            if x["source_role"]=="assistant":auth="conversation_history"
            elif x["source_role"]=="derived":auth="derived_history"
            elif x["claim_id"] in conflicted and x["status"]=="active":auth="user_conflict"
            elif x["status"]=="active":auth="user_state"
            else:auth="user_history"
            out.append({"text":x["claim_text"],"authority":auth,
                        "source_id":self._external_sid(x["source_message_id"])})
        # Raw assistant sources remain useful conversation history even when structural
        # projection correctly emitted no semantic claim.
        for s in self.store.source_history():
            if s["lifecycle"]!="active" or s["source_role"]!="assistant":continue
            ext=self._external_sid(s["source_message_id"])
            if not any(r["source_id"]==ext and r["text"]==s["source_text"] for r in out):
                out.append({"text":s["source_text"],"authority":"conversation_history","source_id":ext})
        return out

    def retrieve(self,query,limit=7):
        # Claim FTS first, then source-history lexical fallback for assistant raw history.
        rows=[]
        seen=set()
        for r in self.store.recall(query,mode="history",limit=max(limit*3,12)):
            ext=self._external_sid(r["source_message_id"])
            item={"text":r["text"],"authority":r["authority"],"source_id":ext}
            key=(item["text"],item["authority"],item["source_id"])
            sc=lexical_score(query,item["text"])
            if key not in seen and sc[0]>0:
                seen.add(key);rows.append((sc,item))
        for s in self.store.source_history():
            if s["lifecycle"]!="active":continue
            # Raw user source is provenance, not automatically model-visible memory.
            if s["source_role"]!="assistant":continue
            item={"text":s["source_text"],"authority":"conversation_history",
                  "source_id":self._external_sid(s["source_message_id"])}
            key=(item["text"],item["authority"],item["source_id"])
            if key in seen:continue
            sc=lexical_score(query,item["text"])
            if sc[0]>0:
                seen.add(key);rows.append((sc,item))
        rows.sort(key=lambda z:(-z[0][0],-z[0][1],z[1]["source_id"],z[1]["text"]))
        return [x for _,x in rows[:limit]]

    def answer(self,question):
        rr=self.retrieve(question,limit=7)
        supported=select_supported(question,rr)
        if not supported:
            return None,True,rr
        return supported[0]["text"],False,rr

    def source_count(self):
        return int(self.store.db.execute("SELECT count(*) FROM source_messages").fetchone()[0])

    def semantic_duplicate_count(self):
        # Duplicate semantic rows for the exact same source+text should not multiply.
        row=self.store.db.execute(
            "SELECT COALESCE(MAX(n),0) FROM (SELECT count(*) n FROM claims GROUP BY source_message_id,claim_text_hash)"
        ).fetchone()
        return int(row[0] or 0)

def public_canary_receipt(case_id):
    """Verify existing public canary receipt/result only; never call provider."""
    cid=str(case_id)
    if cid.startswith("public-"):cid=cid[len("public-"):]
    rp=CANARY_RUNTIME/"responses"/(cid+".json")
    outp=CANARY_RUNTIME/"results"/(cid+".json")
    if not rp.is_file() or not outp.is_file():
        raise FileNotFoundError("existing_canary_receipt_missing:"+cid)
    receipt=json.loads(rp.read_text("utf-8"))
    result=json.loads(outp.read_text("utf-8"))
    return {
      "case_id":cid,
      "receipt_sha256":hashlib.sha256(rp.read_bytes()).hexdigest(),
      "result_sha256":hashlib.sha256(outp.read_bytes()).hexdigest(),
      "call_id":receipt.get("call_id"),
      "manifest_sha256":receipt.get("manifest_sha256"),
      "semantic_validation":result.get("semantic_validation")
    }
