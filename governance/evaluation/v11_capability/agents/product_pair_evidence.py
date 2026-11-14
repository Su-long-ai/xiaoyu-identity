# -*- coding:utf-8 -*-
"""Validate real paired-answer and independent grading bytes, not boolean claims.

Currently supports public24 native product answer artifacts and their frozen
judges; other evaluation suites remain research-only until registered adapter.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from cost_ledger import cost_cny
def _cost_matches(provided,original_usage):
 try:
  usage=original_usage or {}
  expected=cost_cny(usage.get("prompt_tokens",0),usage.get("completion_tokens",0))
  return abs(float(provided)-expected)<0.000001
 except (TypeError,ValueError):return False
def hash_of(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def _check_locomo200(bundle,rows,baseline_sha,candidate_sha):
 try:
  files={}
  for name in ("baseline_answers","candidate_answers","baseline_judgments","candidate_judgments"):
   path=Path(bundle[name+"_path"]).resolve()
   if not path.is_file() or hash_of(path)!=bundle[name+"_sha256"]:return False
   files[name]=json.loads(path.read_text("utf8"))
  b,c,bj,cj=(files[x] for x in
       ("baseline_answers","candidate_answers","baseline_judgments","candidate_judgments"))
  if b.get("status")!="COMPLETE" or c.get("status")!="COMPLETE":return False
  if b.get("completed")!=200 or c.get("completed")!=200:return False
  if b.get("g26_sha")!=baseline_sha or c.get("g27_sha")!=candidate_sha:return False
  if b.get("dataset_sha256")!=c.get("dataset_sha256"):return False
  if bj.get("predictions_sha256")!=bundle["baseline_answers_sha256"]:return False
  if cj.get("predictions_sha256")!=bundle["candidate_answers_sha256"]:return False
  if len(rows)!=200:return False
  bas={x["blind_id"]:x for x in b["rows"]}
  can={x["blind_id"]:x for x in c["rows"]}
  label_b={x["blind_id"]:x for x in bj["rows"]}
  label_c={x["blind_id"]:x for x in cj["rows"]}
  ids={x["id"] for x in rows}
  if not (len(bas)==len(can)==len(label_b)==len(label_c)==len(ids)==200):return False
  if not (set(bas)==set(can)==set(label_b)==set(label_c)==ids):return False
  categories={"1":"multi_hop","2":"temporal","3":"open_domain","4":"single_hop"}
  for x in rows:
   i=x["id"];bb=bas[i];cc=can[i];jb=label_b[i];jc=label_c[i]
   if bb["question"]!=cc["question"] or bb["sample_id"]!=cc["sample_id"]:return False
   if bb["g26_sha"]!=baseline_sha or cc["g27_sha"]!=candidate_sha:return False
   if bb.get("synthetic_authority")!="owner_supplied_transcript_simulation":return False
   if cc.get("synthetic_authority")!="owner_supplied_transcript_simulation":return False
   if not bb.get("answer") or not cc.get("answer"):return False
   if bb["arm"]!="R" or cc["arm"]!="R":return False
   if jb["category"]!=jc["category"] or categories.get(jb["category"])!=x["type"]:return False
   if bool(jb["correct"])!=x["baseline_correct"] or bool(jc["correct"])!=x["candidate_correct"]:
    return False
   for key,original in (("baseline_cost_cny",bb),("candidate_cost_cny",cc)):
    if key in x and not _cost_matches(x[key],original.get("usage")):return False
  return True
 except (OSError,KeyError,ValueError,TypeError,IndexError,UnicodeError,json.JSONDecodeError):
  return False

def _check_dated60(bundle,rows,baseline_sha,candidate_sha):
 try:
  answer_path=Path(bundle["answers_path"]).resolve()
  judge_path=Path(bundle["judgments_path"]).resolve()
  mapping_path=Path(bundle["source_mapping_path"]).resolve()
  checks=((answer_path,"answers_sha256"),(judge_path,"judgments_sha256"),
          (mapping_path,"source_mapping_sha256"))
  if any(not path.is_file() or hash_of(path)!=bundle[key] for path,key in checks):
   return False
  a=json.loads(answer_path.read_text("utf8"))
  j=json.loads(judge_path.read_text("utf8"))
  mapping=json.loads(mapping_path.read_text("utf8"))
  if j.get("predictions_sha256")!=hash_of(answer_path):return False
  if mapping.get("gold_not_loaded") is not True:return False
  if mapping.get("dataset_sha256")!=a.get("dataset_sha256"):return False
  if len(rows)!=60 or len(a.get("rows",[]))!=120 or len(j.get("rows",[]))!=120:
   return False
  bas=str(bundle.get("baseline_arm"))
  can=str(bundle.get("candidate_arm"))
  if bas==can or bas!="G26" or can!="G28":return False
  answers={(r["blind_id"],r["arm"]):r for r in a["rows"]}
  labels={(r["blind_id"],r["arm"]):r for r in j["rows"]}
  if len(answers)!=len(labels)!=120:return False
  if len(answers)!=120 or len(labels)!=120 or set(answers)!=set(labels):return False
  seen=set()
  for row in rows:
   ident=row["id"]
   if ident in seen or row["type"]!="temporal":return False
   seen.add(ident)
   b,c=answers[(ident,bas)],answers[(ident,can)]
   bj,cj=labels[(ident,bas)],labels[(ident,can)]
   if b["manifest_sha256"]!=baseline_sha or c["manifest_sha256"]!=candidate_sha:return False
   if b["dataset_sha256"]!=c["dataset_sha256"] or c["dataset_sha256"]!=a["dataset_sha256"]:return False
   if b["source_date_policy"]!=c["source_date_policy"] or c["source_date_policy"]!="exact_public_session_match":return False
   if b["question"]!=c["question"] or b["sample_id"]!=c["sample_id"]:return False
   if any(b.get(k)!=c.get(k) for k in
         ("dated_memory_count","ambiguous_excluded","unmatched_excluded")):return False
   if not b.get("answer") or not c.get("answer"):return False
   if type(bj["correct"]) is not bool or type(cj["correct"]) is not bool:return False
   if bj["correct"]!=row["baseline_correct"] or cj["correct"]!=row["candidate_correct"]:
    return False
   for field,record in (("baseline_cost_cny",b),("candidate_cost_cny",c)):
    if field in row and not _cost_matches(row[field],record.get("usage")):return False
   for field,record in (("baseline_latency_ms",b),("candidate_latency_ms",c)):
    if field in row and abs(float(row[field])-float(record["elapsed_s"])*1000)>1.1:return False
  return True
 except (OSError,KeyError,ValueError,TypeError,IndexError,UnicodeError,json.JSONDecodeError):
  return False


def _check_qq12(bundle,rows,baseline_sha,candidate_sha):
 try:
  files={}
  for typ in ("answers","judgments","owner_source_input"):
   p=Path(bundle[typ+"_path"]).resolve()
   if not p.is_file() or hash_of(p)!=bundle[typ+"_sha256"]:return False
   files[typ]=json.loads(p.read_text("utf8"))
  a=files["answers"];jud=files["judgments"];inputs=files["owner_source_input"]
  if not (a.get("status")=="COMPLETE" and len(a.get("predictions",[]))==24):return False
  if jud.get("predictions_sha256")!=bundle["answers_sha256"]:return False
  if a["input_sha256"]!=bundle["owner_source_input_sha256"]:return False
  if inputs.get("contains_gold_answers") is not False:return False
  if len(rows)!=12 or len(jud.get("rows",[]))!=24:return False
  original={x["id"]:x for x in inputs["examples"]}
  if len(original)!=12:return False
  answers={(x["id"],x["arm"]):x for x in a["predictions"]}
  labels={(x["id"],x["arm"]):x for x in jud["rows"]}
  if len(answers)!=len(labels)!=24:return False
  if len(answers)!=24 or len(labels)!=24 or set(answers)!=set(labels):return False
  seen=set()
  for case in rows:
   ident=case["id"]
   if ident in seen or ident not in original: return False
   seen.add(ident)
   b,c=answers[(ident,"G28")],answers[(ident,"G29")]
   jb,jc=labels[(ident,"G28")],labels[(ident,"G29")]
   source=original[ident]
   if b["manifest_sha256"]!=baseline_sha or c["manifest_sha256"]!=candidate_sha:
    return False
   if not (b["input_sha256"]==c["input_sha256"]==a["input_sha256"]):return False
   if b["question"]!=c["question"] or c["question"]!=source["question"]:return False
   if b["source_history_sha256"]!=c["source_history_sha256"]:return False
   if b["source_event_time"]!=c["source_event_time"] or c["source_event_time"]!=source["owner_qq_timestamp"]:
    return False
   if case["type"]!=source["type"] or jb["type"]!=jc["type"] or jc["type"]!=case["type"]:
    return False
   if source["operation"]=="owner" and (b["valid_date_records"]!=0 or c["valid_date_records"]<1):
    return False
   if not b.get("source_auth_checked") or not c.get("source_auth_checked"):return False
   if b.get("qq_sent") or c.get("qq_sent") or b.get("qq_network_opened") or c.get("qq_network_opened"):
    return False
   if b.get("status")!="ANSWERED" or c.get("status")!="ANSWERED":return False
   if not b.get("answer") or not c.get("answer"):return False
   if type(jb.get("correct")) is not bool or type(jc.get("correct")) is not bool:return False
   if jb["correct"]!=case["baseline_correct"] or jc["correct"]!=case["candidate_correct"]:
    return False
   for field,rec in (("baseline_cost_cny",b),("candidate_cost_cny",c)):
    if field in case and not _cost_matches(case[field],rec.get("usage")):return False
   for field,rec in (("baseline_latency_ms",b),("candidate_latency_ms",c)):
    if field in case and abs(float(case[field])-float(rec["elapsed_ms"]))>1.1:return False
  return True
 except (OSError,KeyError,ValueError,TypeError,IndexError,UnicodeError,json.JSONDecodeError):
  return False


def _check_composition12(bundle,rows,baseline_sha,candidate_sha):
 try:
  files={}
  for label in ("answers","judgments","owner_source_input"):
   path=Path(bundle[label+"_path"]).resolve()
   if not path.is_file() or hash_of(path)!=bundle[label+"_sha256"]:return False
   files[label]=json.loads(path.read_text("utf8"))
  answer=files["answers"];jud=files["judgments"];original=files["owner_source_input"]
  if len(rows)!=12 or len(answer.get("predictions",[]))!=24:return False
  if original.get("contains_gold") is not False:return False
  if len(original.get("examples",[]))!=12:return False
  if answer.get("status")!="COMPLETE":return False
  if answer.get("dataset_sha256")!=bundle["owner_source_input_sha256"]:return False
  if (jud.get("answer_source_sha256") or jud.get("sealed_g31_g32_sha256") or jud.get("source_g31_g32_sha256"))!=bundle["answers_sha256"]:return False
  examples={x["id"]:x for x in original["examples"]}
  pred={(x["id"],x["arm"]):x for x in answer["predictions"]}
  label={(x["id"],x["arm"]):x for x in jud["rows"]}
  if len(examples)!=12 or len(pred)!=24 or len(label)<24:return False
  if not any(x.get("g31_active") is True for (case,arm),x in pred.items() if arm==bundle.get("candidate_arm")):
   return False
  if (bundle.get("baseline_arm"),bundle.get("candidate_arm")) not in (("G31","G32"),("G32","G34")):return False
  seen=set()
  for item in rows:
   cid=item["id"]
   if cid in seen or cid not in examples:return False
   seen.add(cid)
   a,b=pred[(cid,bundle["baseline_arm"])],pred[(cid,bundle["candidate_arm"])]
   j,k=label[(cid,bundle["baseline_arm"])],label[(cid,bundle["candidate_arm"])]
   x=examples[cid]
   if a["manifest_sha256"]!=baseline_sha or b["manifest_sha256"]!=candidate_sha:return False
   if not (a["dataset_sha256"]==b["dataset_sha256"]==bundle["owner_source_input_sha256"]):
    return False
   if a["question"]!=b["question"] or b["question"]!=x["question"]:return False
   if not a["final_answer"] or not b["final_answer"]:return False
   if a["source_history_sha256"]!=b["source_history_sha256"]:return False
   computed=hashlib.sha256(json.dumps({
     "facts":x["facts"],"unrelated":x["unrelated"],"operation":x["operation"],
     "original_source_event":x["source_event_group"]},
     ensure_ascii=False,sort_keys=True).encode("utf8")).hexdigest()
   if computed!=a["source_history_sha256"]:return False
   if b.get("original_source_event")!=a.get("original_source_event")!=x["source_event_group"]:
    return False
   if j["type"]!=k["type"] or k["type"]!=item["type"]:return False
   if type(j.get("correct")) is not bool or type(k.get("correct")) is not bool:return False
   if j["correct"]!=item["baseline_correct"] or k["correct"]!=item["candidate_correct"]:
    return False
   if not a.get("source_auth_checked") or not b.get("source_auth_checked"):return False
   if not a.get("no_qq_send") or not b.get("no_qq_send"):return False
   if type(b.get("g31_active")) is not bool:return False
   for field,r in (("baseline_cost_cny",a),("candidate_cost_cny",b)):
    if field in item and not _cost_matches(item[field],r.get("usage")):return False
   for field,r in (("baseline_latency_ms",a),("candidate_latency_ms",b)):
    if field in item and abs(float(item[field])-float(r["latency_ms"]))>1.1:return False
  return True
 except (OSError,KeyError,ValueError,TypeError,IndexError,UnicodeError,json.JSONDecodeError):
  return False



def _check_composition12_split(bundle, rows, baseline_sha, candidate_sha):
 """Check strict paired final answers with separate frozen baseline/candidate judge lineage."""
 try:
  names=("answers","baseline_answers","baseline_judgments",
         "candidate_judgments","owner_source_input")
  files={}
  for name in names:
   p=Path(bundle[name+"_path"]).resolve()
   if not p.is_file() or hash_of(p)!=bundle[name+"_sha256"]:return False
   files[name]=json.loads(p.read_text("utf8"))
  answer,prior=files["answers"],files["baseline_answers"]
  bj,cj=files["baseline_judgments"],files["candidate_judgments"]
  inp=files["owner_source_input"]
  base=str(bundle.get("baseline_arm"))
  cand=str(bundle.get("candidate_arm"))
  if base==cand or not base.startswith("G") or not cand.startswith("G"):return False
  n=len(rows)
  if not (n>=4 and answer.get("status")=="COMPLETE"
          and len(answer.get("predictions",[]))==2*n
          and prior.get("status")=="COMPLETE"
          and len(prior.get("predictions",[]))==2*n):return False
  if inp.get("contains_gold") is not False or len(inp.get("examples",[]))!=n:return False
  if answer.get("gold_visible_to_answers") is not False:return False
  if not (answer.get("dataset_sha256")==prior.get("dataset_sha256")
          ==bundle["owner_source_input_sha256"]):return False
  if answer.get("baseline_manifest_sha256")!=baseline_sha:return False
  if answer.get("candidate_manifest_sha256")!=candidate_sha:return False
  if prior.get("candidate_manifest_sha256")!=baseline_sha:return False
  if (bj.get(bundle.get("baseline_judgments_answer_field","sealed_g31_g32_sha256"))!=bundle["baseline_answers_sha256"]
      or cj.get(bundle.get("candidate_judgments_answer_field","source_sha256"))!=bundle["answers_sha256"]):return False
  examples={x["id"]:x for x in inp["examples"]}
  preds={(x["id"],x["arm"]):x for x in answer["predictions"]}
  oldpreds={(x["id"],x["arm"]):x for x in prior["predictions"]}
  base_labels={(x["id"],x["arm"]):x for x in bj["rows"]}
  cand_labels={(x["id"],x["arm"]):x for x in cj["rows"]}
  if len(examples)!=n or len(preds)!=2*n or len(oldpreds)!=2*n:return False
  if len(cand_labels)!=n or sum((i,cand) in cand_labels for i in examples)!=n:return False
  changed=0
  if {x["id"] for x in rows}!=set(examples):return False
  for row in rows:
   case=row["id"]; src=examples[case]
   a,b=preds[(case,base)],preds[(case,cand)]
   past=oldpreds[(case,base)]
   j,k=base_labels[(case,base)],cand_labels[(case,cand)]
   # Baseline is reused exact prior response, not resampled under unequal cache state.
   if a!=past:return False
   if a["manifest_sha256"]!=baseline_sha or b["manifest_sha256"]!=candidate_sha:return False
   if a["dataset_sha256"]!=b["dataset_sha256"]:return False
   if a["question"]!=b["question"] or b["question"]!=src["question"]:return False
   expected=hashlib.sha256(json.dumps({
    "facts":src["facts"],"unrelated":src["unrelated"],
    "operation":src["operation"],"original_source_event":src["source_event_group"]
   },ensure_ascii=False,sort_keys=True).encode("utf8")).hexdigest()
   if a["source_history_sha256"]!=b["source_history_sha256"] or expected!=a["source_history_sha256"]:
    return False
   if a["original_source_event"]!=b["original_source_event"] or b["original_source_event"]!=src["source_event_group"]:
    return False
   if not a.get("final_answer") or not b.get("final_answer"):return False
   if not all(x.get("source_auth_checked") and x.get("no_qq_send") for x in (a,b)):return False
   if not (j["type"]==k["type"]==row["type"]):return False
   if type(j.get("correct")) is not bool or type(k.get("correct")) is not bool:return False
   if j["correct"]!=row["baseline_correct"] or k["correct"]!=row["candidate_correct"]:return False
   changed+=a.get("admitted_source_ids")!=b.get("admitted_source_ids")
  if changed<1 or changed!=bundle.get("changed_evidence_case_count"):return False
  return True
 except (OSError,KeyError,ValueError,TypeError,IndexError,UnicodeError,json.JSONDecodeError):
  return False



def _check_g71_g69_full200_h(bundle,rows,baseline_sha,candidate_sha):
 """Verify G56 original + G69 exact runtime 200 source/prediction/grade bytes.

 No gold or score is passed into the verifier as authority; all final-answer
 boolean claims must match SHA-sealed original paired source artifacts.
 """
 try:
  names=("baseline_first_answers","baseline_second_answers",
    "baseline_first_judgments","baseline_second_judgments",
    "candidate_frozen_selection","candidate_prediction_seal",
    "candidate_full200_grade","candidate_scopes")
  content={}
  for name in names:
   path=Path(bundle[name+"_path"]).resolve()
   if not path.is_file() or hash_of(path)!=bundle[name+"_sha256"]:return False
   content[name]=json.loads(path.read_text("utf8"))
  b0=content["baseline_first_answers"];b1=content["baseline_second_answers"]
  bj0=content["baseline_first_judgments"];bj1=content["baseline_second_judgments"]
  sel=content["candidate_frozen_selection"];seal=content["candidate_prediction_seal"]
  grade=content["candidate_full200_grade"];scopes=content["candidate_scopes"]
  if len(rows)!=200 or len({x["id"] for x in rows})!=200:return False
  if not (len(b0.get("rows",[]))==len(b1.get("rows",[]))==100
          and len(bj0.get("rows",[]))==len(bj1.get("rows",[]))==100):
   return False
  if b0.get("gold_read") is not False or b1.get("gold_read") is not False:
   return False
  if b0.get("g54_manifest_sha")!=baseline_sha or b1.get("g54_manifest_sha")!=baseline_sha:
   return False
  if b0.get("dataset_sha")!=b1.get("dataset_sha"):return False
  if sel.get("count")!=200 or sel.get("model_rc_sha256")!=candidate_sha:
   return False
  if sel.get("gold_category_evidence_not_loaded") is not True:return False
  if sel.get("blind_input_sha256")!=b0.get("dataset_sha"):return False
  if seal.get("count")!=200 or seal.get("manifest_sha256")!=candidate_sha:return False
  if seal.get("selection_sha256")!=bundle["candidate_frozen_selection_sha256"]:
   return False
  if seal.get("scope_sha256")!=bundle["candidate_scopes_sha256"]:
   return False
  if seal.get("category_and_gold_not_read") is not True:return False
  if grade.get("n")!=200 or grade.get("status")!="COMPLETE":return False
  if grade.get("product_candidate_sha256")!=candidate_sha:return False
  if grade.get("gold_read_only_after_200_prediction_seal") is not True:
   return False
  base={x["blind_id"]:x for x in b0["rows"]+b1["rows"]}
  old_j={x["blind_id"]:x for x in bj0["rows"]+bj1["rows"]}
  new_j={x["blind_id"]:x for x in grade["rows"]}
  ids={x["id"] for x in rows}
  freezes={x["blind_id"]:x for x in sel["question_items"]}
  if not (len(base)==len(old_j)==len(new_j)==len(freezes)==len(ids)==200):return False
  if not (set(base)==set(old_j)==set(new_j)==set(freezes)==ids):return False
  samples={}
  for sid,info in seal["sample_answer_hashes"].items():
   path=Path(bundle["candidate_sample_answer_paths"][sid]).resolve()
   if not path.is_file() or hash_of(path)!=info["sha256"]:return False
   d=json.loads(path.read_text("utf8"))
   if (d.get("status")!="COMPLETE" or d.get("gold_read") is not False
       or d.get("candidate_manifest_sha")!=candidate_sha
       or d.get("frozen_selection_sha")!=bundle["candidate_frozen_selection_sha256"]
       or d.get("m2_task")!=scopes["tasks"].get(sid)):return False
   if len(d["rows"])!=info["n"] or not (d["done"]==d["target"]==len(d["rows"])):
    return False
   for x in d["rows"]:
    ident=x["blind_id"]
    if ident in samples:return False
    if x["manifest_sha256"]!=candidate_sha or x["status"]!="ANSWERED":return False
    samples[ident]=x
  if len(samples)!=200 or set(samples)!=ids:return False
  categories={"1":"multi_hop","2":"temporal","3":"open_domain","4":"single_hop"}
  wins=losses=0
  for x in rows:
   i=x["id"];b=base[i];g=old_j[i];c=samples[i];j=new_j[i]
   if (b.get("arm")!="H" or b.get("g54_manifest_sha")!=baseline_sha
       or b["sample_id"]!=c["sample_id"] or b["question"]!=c["question"]
       or c["sample_id"]!=freezes[i]["sample_id"]
       or c["question"]!=freezes[i]["question"]):
    return False
   if (x["type"]!=categories.get(str(g["category"]))
       or str(j["category"])!=str(g["category"])):return False
   if (b["answer"]!=j["g56_answer"] or c["answer"]!=j["g69_answer"]):
    return False
   if (bool(g["h_correct"])!=j["g56_h_correct_original"]
       or bool(g["h_correct"])!=x["baseline_correct"]
       or j["g69_h_correct_same_rubric"]!=x["candidate_correct"]):
    return False
   if j["answers_exactly_identical"]!=(b["answer"]==c["answer"]):return False
   wins+=int(x["candidate_correct"] and not x["baseline_correct"])
   losses+=int(x["baseline_correct"] and not x["candidate_correct"])
  base_correct=sum(x["baseline_correct"] for x in rows)
  candidate_correct=sum(x["candidate_correct"] for x in rows)
  return (grade.get("g56_h_correct")==base_correct
      and grade.get("g69_h_correct")==candidate_correct
      and grade.get("wins")==wins and grade.get("losses")==losses)
 except (OSError,KeyError,ValueError,TypeError,IndexError,UnicodeError,json.JSONDecodeError):
  return False


def check_output_integrity(bundle, rows):
 """Gate all supported raw output receipts by actual SHA-bound provider bytes.

 Explicitly malformed/length-truncated answers are invalidated in score
 arithmetic. Missing historical finish metadata merely prevents an
 unsupported pilot claim; it is not evidence that an answer was false.
 """
 try:
  from answer_receipt_adapters import collect
  from answer_outcome_gate import inspect_answer, requested_fields_no_gold
  recs=collect(bundle,rows)
  if recs is None:
   return {"verified":False,"reason":"raw_output_integrity_adapter_not_registered"}
  bad=[];invalid_base=[];invalid_cand=[];unknown=0
  for case in rows:
   ident=case["id"]
   for arm,label in (("baseline",invalid_base),("candidate",invalid_cand)):
    record=recs[ident][arm]
    status=inspect_answer(record["text"],record["finish_reason"])
    fields=requested_fields_no_gold(record.get("question"),record["text"])
    invalid=status["status"]=="invalid" or bool(fields["missing"])
    if status["status"]=="valid" and not invalid:
     continue
    bad.append([ident,arm,"invalid" if invalid else status["status"],
                status["errors"],status["warnings"],
                {"missing_requested_fields":fields["missing"]}])
    if invalid:
     label.append(ident)
    else:
     unknown+=1
  return {"verified":not bad,
          "reason":"all_outputs_complete" if not bad else "bad_or_unverifiable_outputs",
          "raw_output_count":2*len(rows),
          "unverified_finish_count":unknown,
          "failures":bad[:20],
          "invalid_baseline_ids":invalid_base,
          "invalid_candidate_ids":invalid_cand}
 except (OSError,KeyError,ValueError,TypeError,IndexError,UnicodeError,
         json.JSONDecodeError) as exc:
  return {"verified":False,"reason":"raw_output_integrity_check_error",
          "error_type":type(exc).__name__}

def check(bundle, rows, baseline_sha, candidate_sha):
 if isinstance(bundle,dict) and bundle.get("kind")=="g71_g69_full200_h_real_paired_v1":
  return _check_g71_g69_full200_h(bundle,rows,baseline_sha,candidate_sha)
 if bundle is None:return False
 if isinstance(bundle,dict) and bundle.get("kind")=="owner_composition12_split_judges_v1":
  return _check_composition12_split(bundle,rows,baseline_sha,candidate_sha)
 if isinstance(bundle,dict) and bundle.get("kind")=="owner_composition12_real_paired_v1":
  return _check_composition12(bundle,rows,baseline_sha,candidate_sha)
 if isinstance(bundle,dict) and bundle.get("kind")=="qq12_real_owner_eventtime_v1":
  return _check_qq12(bundle,rows,baseline_sha,candidate_sha)
 if isinstance(bundle,dict) and bundle.get("kind")=="dated_temporal60_real_answers_v1":
  return _check_dated60(bundle,rows,baseline_sha,candidate_sha)
 if isinstance(bundle,dict) and bundle.get("kind")=="locomo200_synthetic_real_answers_v1":
  return _check_locomo200(bundle,rows,baseline_sha,candidate_sha)
 if not isinstance(bundle,dict) or bundle.get("kind")!="public24_real_product_answers_v1":
  return False
 try:
  p=Path(bundle["answers_path"]).resolve()
  j=Path(bundle["judgments_path"]).resolve()
  if not p.is_file() or not j.is_file():return False
  if hash_of(p)!=bundle.get("answers_sha256") or hash_of(j)!=bundle.get("judgments_sha256"):return False
  a=json.loads(p.read_text("utf8"));v=json.loads(j.read_text("utf8"))
  if a.get("status")!="COMPLETE" or v.get("answer_sha256")!=hash_of(p):
   return False
  answers=a["predictions"];judgments=v["judgments"]
  if len(answers)!=len(judgments) or len(answers)!=2*len(rows):return False
  base=str(bundle.get("baseline_arm") or "G26")
  cand=str(bundle.get("candidate_arm") or "G27")
  by={(x["id"],x["arm"]):x for x in answers}
  labels={(x["id"],x["arm"]):x for x in judgments}
  if len(by)!=len(labels)!=2*len(rows):return False
  if len(by)!=2*len(rows) or len(labels)!=2*len(rows):return False
  if set(by)!=set(labels):return False
  for case in rows:
   cid=case["id"]
   b,c=by[(cid,base)],by[(cid,cand)]
   bj,cj=labels[(cid,base)],labels[(cid,cand)]
   if b["manifest_sha256"]!=baseline_sha or c["manifest_sha256"]!=candidate_sha:
    return False
   if b["question"]!=c["question"] or b["source_history_sha256"]!=c["source_history_sha256"]:
    return False
   if b["dataset_sha256"]!=c["dataset_sha256"]!=a["input_sha256"]:
    return False
   if b.get("status")!="ANSWERED" or c.get("status")!="ANSWERED":return False
   if not b.get("source_auth_checked") or not c.get("source_auth_checked"):return False
   if not c.get("route_observed") or not b.get("route_observed"):return False
   if not str(b.get("response") or "").strip() or not str(c.get("response") or "").strip():
    return False
   if bj["type"]!=case["type"] or cj["type"]!=case["type"]:return False
   if type(bj["correct"]) is not bool or type(cj["correct"]) is not bool:return False
   if bj["correct"]!=case["baseline_correct"] or cj["correct"]!=case["candidate_correct"]:
    return False
   for key,original in (("baseline_cost_cny",b),("candidate_cost_cny",c)):
    if key in case and not _cost_matches(case[key],original.get("usage")):return False
  return True
 except (OSError,KeyError,ValueError,TypeError,IndexError,UnicodeError,json.JSONDecodeError):
  return False
