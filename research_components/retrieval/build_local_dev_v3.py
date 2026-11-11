# -*- coding: utf-8 -*-
from __future__ import annotations
import json, hashlib, random
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).with_name("local_dev_v3_240.json")
SEED=20261102
rng=random.Random(SEED)

TWO=[
"Avery Stone","Bianca Reed","Caleb North","Diana Vale","Evan Cross","Farah Lane","Gavin Moss","Hana Blake",
"Iris Cole","Jonas Pike","Keira Frost","Liam Hart","Maya Quinn","Nolan Sage","Opal Reed","Priya West",
"Quentin Shaw","Rina Brooks","Samir Dale","Tessa Moon","Uma Park","Victor Hale","Wendy Fox","Xavier King",
"Yara Lake","Zane Field","Alina Marsh","Boris Kent","Cora Mills","Derek Snow","Elena Woods","Felix Grant",
"Greta Bell","Hugo Price","Ines Rose","Jasper Green","Kara Young","Leo Scott","Mina Gray","Noah Brown"
]
ONE=["Avery","Bianca","Caleb","Diana","Evan","Farah","Gavin","Hana","Iris","Jonas","Keira","Liam","Maya","Nolan","Opal","Priya","Quinn","Rina","Samir","Tessa","Uma","Victor","Wendy","Xavier","Yara","Zane","Alina","Boris","Cora","Derek","Elena","Felix","Greta","Hugo","Ines","Jasper","Kara","Leo","Mina","Noah"]
CITIES=["Oslo","Kyoto","Denver","Lisbon","Tallinn","Vienna","Prague","Seoul","Warsaw","Dublin","Porto","Busan","Lyon","Sofia","Quito","Madrid","Ghent","Malmo","Naples","Helsinki"]
ITEMS=["blue mug","red notebook","silver keychain","green scarf","orange thermos","black umbrella","yellow backpack","white camera","purple journal","brown satchel","teal bottle","navy cap","gold pen","gray blanket","pink lantern","copper bell","ivory vase","crimson wallet","jade box","amber clock"]
HOBBIES=["cello","violin","piano","guitar","flute","drums","harp","saxophone","trumpet","clarinet","banjo","mandolin","ukulele","bassoon","lute","sitar","accordion","trombone","marimba","cornet"]
PREFS=["matcha","oolong tea","black coffee","sparkling water","chai","lemon tea","cold brew","mint tea","cocoa","green tea"]
ROLES=["pediatrician","architect","teacher","mechanic","designer","researcher","chef","nurse","engineer","librarian"]
ORG=["Aurora Studio","Cedar Group","Harbor Works","Nimbus Lab","Maple Office","Quartz Center","Pine House","Delta Workshop","Amber Circle","Cobalt Team"]
BOOKS=["North Wind","Glass Harbor","Silent Orbit","Blue Archive","Paper Moon","River Signal","Winter Atlas","Hidden Garden","Copper Sky","Last Lantern"]

def h(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dt(month,day,hour=9,year=2025):
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:00:00Z"

def pick_name(i, single_ratio=0.45):
    return ONE[i%len(ONE)] if ((i*7)%100)<int(single_ratio*100) else TWO[i%len(TWO)]

def mem(mid,text,t):
    return {"id":mid,"text":text,"time":t}

cases=[]
def add(cid,fam,q,exp,req,mems):
    cases.append({"id":cid,"family":fam,"question":q,"expected":[exp] if isinstance(exp,str) else list(exp),"required_ids":list(req),"memories":mems})

# 1) single-hop semantic / surface variation: 30
for i in range(30):
    p=pick_name(i,0.5); role=ROLES[i%len(ROLES)]; org=ORG[(i*3)%len(ORG)]
    cid=f"SH-{i+1:03d}"; a=f"SH_{i+1:03d}_A"; x=f"SH_{i+1:03d}_X"
    variants=[
      (f"{p} earns a living as a {role} at {org}.", f"What does {p} do for work?"),
      (f"At {org}, {p}'s day job is {role}.", f"What is {p}'s occupation?"),
      (f"{p} mentioned working professionally as a {role} for {org}.", f"Which profession does {p} have?")
    ]
    t,q=variants[i%3]
    add(cid,"single_hop_semantic",q,role,[a],[mem(a,t,dt(1,(i%27)+1)),mem(x,f"{pick_name(i+9)} recently visited {org} for an unrelated event.",dt(1,(i%27)+1,11))])

# 2) varied two-hop relations: 40
for i in range(40):
    cid=f"M2V-{i+1:03d}"; a=f"M2V_{i+1:03d}_A"; b=f"M2V_{i+1:03d}_B"; x=f"M2V_{i+1:03d}_X"
    p=pick_name(i+3,0.55); target=ONE[(i+11)%len(ONE)]; city=CITIES[i%len(CITIES)]; obj=ITEMS[i%len(ITEMS)]
    typ=i%5
    if typ==0:
        ta=f"{target} said the {obj} came from {p} after they met."
        tb=f"{p} is based in {city} and usually works remotely."
        q=f"Which city is home base for the person who passed the {obj} to {target}?"
    elif typ==1:
        book=BOOKS[i%len(BOOKS)]
        ta=f"{p} was the one who recommended the book {book} to {target}."
        tb=f"{p} moved to {city} earlier this year."
        q=f"Where did {target}'s recommender of {book} move?"
    elif typ==2:
        ta=f"{target} usually hikes with {p} on weekends."
        tb=f"{p} now calls {city} home."
        q=f"Where does {target}'s regular hiking partner live now?"
    elif typ==3:
        ta=f"{p} reviewed {target}'s portfolio before the interview."
        tb=f"{p} works from an office in {city}."
        q=f"In which city is the person who reviewed {target}'s portfolio based?"
    else:
        ta=f"For the community fundraiser, {target} coordinated directly with {p}."
        tb=f"{p}'s home city is {city}."
        q=f"What city does {target}'s fundraiser contact call home?"
    add(cid,"multi_hop_2_varied",q,city,[a,b],[
      mem(a,ta,dt(2,(i%27)+1,8)),mem(b,tb,dt(2,(i%27)+1,10)),
      mem(x,f"{pick_name(i+17)} also mentioned {obj} and visited {city}, but was not connected to {target}.",dt(2,(i%27)+1,12))
    ])

# 3) varied three-hop relations: 30
for i in range(30):
    cid=f"M3V-{i+1:03d}"; a=f"M3V_{i+1:03d}_A"; b=f"M3V_{i+1:03d}_B"; c=f"M3V_{i+1:03d}_C"
    p1=pick_name(i+5,0.5); p2=pick_name(i+13,0.5); target=ONE[(i+19)%len(ONE)]; val=HOBBIES[i%len(HOBBIES)]
    typ=i%5
    if typ==0:
        ta=f"{target} gets career advice from {p1}."
        tb=f"{p1} collaborates most often with {p2} on client projects."
        tc=f"Outside work, {p2} performs on the {val}."
        q=f"What instrument does the main collaborator of {target}'s career adviser perform on?"
    elif typ==1:
        ta=f"{target}'s closest study partner is {p1}."
        tb=f"{p1} shares an apartment with {p2}."
        tc=f"{p2} plays the {val} in a neighborhood band."
        q=f"What does the roommate of {target}'s closest study partner play?"
    elif typ==2:
        ta=f"{p1} leads the volunteer project that {target} joined."
        tb=f"{p1}'s assistant on that project is {p2}."
        tc=f"{p2} practices the {val} every evening."
        q=f"Which instrument is practiced by the assistant to the leader of {target}'s volunteer project?"
    elif typ==3:
        ta=f"{target} takes design lessons from {p1}."
        tb=f"{p1} runs a small workshop together with {p2}."
        tc=f"{p2}'s favorite instrument to perform is the {val}."
        q=f"What instrument does the workshop partner of {target}'s design teacher perform?"
    else:
        ta=f"{target} reports to {p1} on the neighborhood committee."
        tb=f"{p1} co-organizes events with {p2}."
        tc=f"{p2} performs the {val} at local events."
        q=f"What does the co-organizer of {target}'s committee lead perform?"
    add(cid,"multi_hop_3_varied",q,val,[a,b,c],[
      mem(a,ta,dt(3,(i%27)+1,8)),mem(b,tb,dt(3,(i%27)+1,9)),mem(c,tc,dt(3,(i%27)+1,10)),
      mem(f"M3V_{i+1:03d}_X",f"{pick_name(i+22)} likes listening to the {HOBBIES[(i+7)%len(HOBBIES)]}, but has no role in this chain.",dt(3,(i%27)+1,12))
    ])

# 4) temporal current state: 30
for i in range(30):
    cid=f"TC-{i+1:03d}"; p=pick_name(i+7,0.5); old=PREFS[i%len(PREFS)]; mid=PREFS[(i+3)%len(PREFS)]; new=PREFS[(i+6)%len(PREFS)]
    a=f"TC_{i+1:03d}_A";b=f"TC_{i+1:03d}_B";c=f"TC_{i+1:03d}_C"
    qv=[f"What drink does {p} prefer these days?",f"What is {p}'s current go-to drink?",f"If choosing now, what drink would {p} pick?"][i%3]
    add(cid,"temporal_current",qv,new,[c],[
      mem(a,f"{p} used to prefer {old}.",dt(1,(i%27)+1,9,2023)),
      mem(b,f"By last year, {p} was alternating between {old} and {mid}.",dt(1,(i%27)+1,9,2024)),
      mem(c,f"These days {p} prefers {new} and orders it most often.",dt(1,(i%27)+1,9,2025))
    ])

# 5) temporal order / composition: 20, requires two memories
for i in range(20):
    cid=f"TO-{i+1:03d}"; p=pick_name(i+10,0.45); city1=CITIES[i%len(CITIES)]; city2=CITIES[(i+5)%len(CITIES)]
    a=f"TO_{i+1:03d}_A";b=f"TO_{i+1:03d}_B";x=f"TO_{i+1:03d}_X"
    add(cid,"temporal_order",f"After leaving {city1}, where did {p} settle next?",city2,[a,b],[
      mem(a,f"In spring 2024, {p} was living in {city1}.",dt(4,(i%27)+1,9,2024)),
      mem(b,f"Later that year, {p} relocated from {city1} to {city2} and settled there.",dt(9,(i%27)+1,9,2024)),
      mem(x,f"{pick_name(i+27)} took a short trip through {city2} around the same time.",dt(9,(i%27)+1,11,2024))
    ])

# 6) alias / identity bridge: 20
for i in range(20):
    cid=f"AL-{i+1:03d}"; full=TWO[(i+6)%len(TWO)]; alias=f"{full.split()[0][0]}{full.split()[1][0]}"; city=CITIES[(i+8)%len(CITIES)]
    a=f"AL_{i+1:03d}_A";b=f"AL_{i+1:03d}_B";x=f"AL_{i+1:03d}_X"
    add(cid,"alias_identity",f"Which city does {full} live in now?",city,[a,b],[
      mem(a,f"{full} often goes by the initials {alias} among friends.",dt(5,(i%27)+1,8)),
      mem(b,f"{alias} recently moved to {city} and plans to stay.",dt(5,(i%27)+1,10)),
      mem(x,f"{pick_name(i+31)} once used the letters {alias} as a project code, unrelated to {full}.",dt(5,(i%27)+1,12))
    ])

# 7) entity collision: 20
for i in range(20):
    cid=f"EC-{i+1:03d}"; first=ONE[(i+2)%len(ONE)]; p1=f"{first} {TWO[(i+4)%len(TWO)].split()[1]}"; p2=f"{first} {TWO[(i+15)%len(TWO)].split()[1]}"
    org1=ORG[i%len(ORG)]; city=CITIES[(i+2)%len(CITIES)]
    a=f"EC_{i+1:03d}_A";b=f"EC_{i+1:03d}_B";x1=f"EC_{i+1:03d}_X1";x2=f"EC_{i+1:03d}_X2"
    add(cid,"entity_collision",f"Where is the {first} who leads {org1} based?",city,[a,b],[
      mem(a,f"{p1} leads {org1}.",dt(6,(i%27)+1,8)),
      mem(b,f"{p1} is based in {city}.",dt(6,(i%27)+1,9)),
      mem(x1,f"{p2} has the same first name but works with {ORG[(i+4)%len(ORG)]}.",dt(6,(i%27)+1,10)),
      mem(x2,f"{p2} once traveled through {city}.",dt(6,(i%27)+1,11))
    ])

# 8) semantic paraphrase / lexical mismatch: 20
for i in range(20):
    cid=f"SP-{i+1:03d}"; p=pick_name(i+14,0.5); role=ROLES[(i+4)%len(ROLES)]
    a=f"SP_{i+1:03d}_A";x=f"SP_{i+1:03d}_X"
    tpls=[
      (f"{p} spends weekdays caring for sick children at a clinic; professionally, {p} is a {role}.",f"What job does {p} have?"),
      (f"{p} said the profession paying the bills is {role}, though weekends are for hobbies.",f"How does {p} earn a living?"),
      (f"When talking about work, {p} described being employed as a {role}.",f"What is {p}'s line of work?")
    ]
    text,q=tpls[i%3]
    add(cid,"semantic_paraphrase",q,role,[a],[mem(a,text,dt(7,(i%27)+1,9)),mem(x,f"{pick_name(i+20)} mentioned the word {role} while discussing someone else.",dt(7,(i%27)+1,11))])

# 9) Chinese / mixed-language memory bridge: 15
cn_cities=["上海","苏州","杭州","南京","成都","深圳","北京","武汉","西安","厦门"]
cn_items=["蓝色杯子","红色笔记本","银色钥匙扣","绿色围巾","黑色雨伞","黄色背包","白色相机","紫色日记本","棕色挎包","金色钢笔"]
for i in range(15):
    cid=f"ZH-{i+1:03d}"; p=ONE[(i+21)%len(ONE)]; target=ONE[(i+29)%len(ONE)]; city=cn_cities[i%len(cn_cities)]; item=cn_items[i%len(cn_items)]
    a=f"ZH_{i+1:03d}_A";b=f"ZH_{i+1:03d}_B";x=f"ZH_{i+1:03d}_X"
    if i%2==0:
        ta=f"{target}说，{item}是{p}送给他的。"; tb=f"{p}现在长期住在{city}。"; q=f"送给{target}{item}的人现在住在哪个城市？"
    else:
        ta=f"{target} mentioned that the {item} came from {p}."; tb=f"{p}现在把{city}当作长期居住地。"; q=f"Where does the person who gave {target} the {item} live now?"
    add(cid,"cross_language",q,city,[a,b],[mem(a,ta,dt(8,(i%27)+1,8)),mem(b,tb,dt(8,(i%27)+1,10)),mem(x,f"{ONE[(i+3)%len(ONE)]}也提到过{item}，但和{target}无关。",dt(8,(i%27)+1,12))])

# 10) abstention / no-answer boundary: 15
for i in range(15):
    cid=f"BD-{i+1:03d}"; p=pick_name(i+25,0.5); a=f"BD_{i+1:03d}_A";x=f"BD_{i+1:03d}_X"
    q=[f"What is {p}'s favorite movie?",f"Which university did {p} graduate from?",f"What is {p}'s favorite dessert?"][i%3]
    add(cid,"boundary_abstain",q,["i don't know","unknown"],[],[
      mem(a,f"{p} enjoys weekend walks and recently bought a desk lamp.",dt(9,(i%27)+1,9)),
      mem(x,f"{p} mentioned a rainy afternoon at the library.",dt(9,(i%27)+1,10))
    ])

assert len(cases)==240
counts={}
for c in cases: counts[c["family"]]=counts.get(c["family"],0)+1

# Global distractors, deliberately mixed single/two-token names and broad paraphrases.
distractors=[]
for i in range(160):
    p=pick_name(i+50,0.5); city=CITIES[(i*7)%len(CITIES)]
    texts=[
      f"{p} attended a weekend market while visiting {city}.",
      f"{p} keeps spare batteries in a kitchen drawer.",
      f"{p} listened to a {HOBBIES[i%len(HOBBIES)]} recital after dinner.",
      f"{p} bought groceries before taking an evening walk.",
      f"{p} read {BOOKS[i%len(BOOKS)]} on a train trip.",
    ]
    distractors.append({"id":f"D3_{i+1:03d}","text":texts[i%len(texts)],"time":dt(((i%12)+1),((i%27)+1),12,2024)})

# IDs globally unique.
ids=[d["id"] for d in distractors]
for c in cases:
    mids=[m["id"] for m in c["memories"]]
    assert set(c["required_ids"])<=set(mids)
    ids.extend(mids)
assert len(ids)==len(set(ids))

obj={
 "schema":"xiaoyu-retrieval-fastlane-local-dev-v3",
 "created_at":"2026-11-02T16:05:00+08:00",
 "role":"PUBLIC_LOCAL_DEVELOPMENT_AND_REGRESSION_GATE",
 "seed":SEED,
 "shared_store":True,
 "context_cap":20,
 "case_count":len(cases),
 "family_counts":counts,
 "notes":"Public DEV set. Broad deterministic synthetic distribution with varied relation graphs, paraphrases, single/two-token entities, temporal composition, aliases, collisions, Chinese/mixed language, and abstention. Not a hidden generalization benchmark. Research agents may inspect and iterate on this set. Local v2_120 remains frozen regression history; auditor-only OOD remains separate.",
 "distractors":distractors,
 "cases":cases
}
OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"path":str(OUT),"sha256":h(OUT),"cases":len(cases),"family_counts":counts,"documents":len(distractors)+sum(len(c["memories"]) for c in cases)},ensure_ascii=False,indent=2))
