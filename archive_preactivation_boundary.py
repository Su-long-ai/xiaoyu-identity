# -*- coding: utf-8 -*-
from __future__ import annotations
import base64, hashlib, json, shutil, sqlite3, tempfile, zipfile
from pathlib import Path

from identity_core import (
    IdentityStore, NAMESPACE, SCHEMA_VERSION, USER_MEMORY_SOURCE_KINDS, dump
)

SQLITE_MAGIC=b"SQLite format 3\x00"
ZIP_MAGICS=(b"PK\x03\x04",b"PK\x05\x06",b"PK\x07\x08")
R13_APP_ID=0x58594649
R13_FORMAT="portable-companion-identity-single-sqlite"
R13_ARCHIVE_VERSION=1
PERSONA_SECTION_LIMIT=2800

class ArchiveQualificationError(ValueError):
    pass

def _norm(v):
    if isinstance(v, bytes):
        return {"__bytes__":base64.b64encode(v).decode()}
    return v

def _logical_root_conn(c):
    h=hashlib.sha256()
    objs=c.execute("""SELECT type,name,tbl_name,sql FROM sqlite_master
                      WHERE name NOT LIKE 'sqlite_%' AND name!='archive_meta'
                      ORDER BY type,name""").fetchall()
    for row in objs:
        h.update(json.dumps([_norm(x) for x in row],ensure_ascii=False,separators=(",",":")).encode("utf-8"))
    tables=[r[0] for r in c.execute("""SELECT name FROM sqlite_master WHERE type='table'
                                      AND name NOT LIKE 'sqlite_%' AND name!='archive_meta' ORDER BY name""")]
    for table in tables:
        q='"'+table.replace('"','""')+'"'
        cols=c.execute(f"PRAGMA table_info({q})").fetchall()
        h.update(json.dumps(["TABLE",table,[[_norm(x) for x in r] for r in cols]],
                            ensure_ascii=False,separators=(",",":")).encode("utf-8"))
        try:
            rows=c.execute(f"SELECT rowid,* FROM {q} ORDER BY rowid").fetchall()
        except sqlite3.OperationalError:
            names=[r[1] for r in cols]
            order=",".join('"'+x.replace('"','""')+'"' for x in names)
            rows=c.execute(f"SELECT * FROM {q} ORDER BY {order}").fetchall()
        for row in rows:
            h.update(json.dumps([_norm(x) for x in row],ensure_ascii=False,separators=(",",":")).encode("utf-8"))
    return h.hexdigest()

def _detect(path):
    head=Path(path).read_bytes()[:16]
    if head.startswith(SQLITE_MAGIC):
        return "single_sqlite"
    if any(head.startswith(x) for x in ZIP_MAGICS):
        return "legacy_zip"
    raise ArchiveQualificationError("Unknown identity archive format")

def _decode_legacy(archive, db_dest):
    with zipfile.ZipFile(archive) as z:
        if set(z.namelist())!={"identity.sqlite3","identity.json","manifest.json"}:
            raise ArchiveQualificationError("Unknown archive contents")
        manifest=json.loads(z.read("manifest.json"))
        version=int(manifest.get("version") or 0)
        if manifest.get("format")!=NAMESPACE or version not in range(1,SCHEMA_VERSION+1):
            raise ArchiveQualificationError("Unsupported identity format")
        contents={n:z.read(n) for n in ("identity.sqlite3","identity.json")}
        for name,blob in contents.items():
            expected=(manifest.get("files") or {}).get(name)
            if not expected or hashlib.sha256(blob).hexdigest()!=expected:
                raise ArchiveQualificationError("Corrupted archive: "+name)
        data=json.loads(contents["identity.json"].decode("utf-8"))
        expected_iid=manifest.get("identity_id")
        if not expected_iid or data.get("persona",{}).get("id")!=expected_iid:
            raise ArchiveQualificationError("Identity mismatch")
        db_dest.write_bytes(contents["identity.sqlite3"])
    return {"format":"legacy_zip","expected_identity_id":expected_iid,"source_schema_version":version}

def _decode_single(archive, db_dest):
    # Object identity first: the exact bytes copied into staging are the only
    # bytes subsequently validated and eligible for activation.
    shutil.copy2(archive,db_dest)
    uri="file:"+Path(db_dest).resolve().as_posix()+"?mode=ro"
    c=sqlite3.connect(uri,uri=True)
    try:
        integrity=c.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity!="ok":
            raise ArchiveQualificationError("archive integrity mismatch")
        app=c.execute("PRAGMA application_id").fetchone()[0]
        uv=c.execute("PRAGMA user_version").fetchone()[0]
        try:
            meta=c.execute("""SELECT format,archive_version,schema_version,identity_id,logical_root
                              FROM archive_meta WHERE id=1""").fetchone()
        except sqlite3.Error as e:
            raise ArchiveQualificationError("wrong archive format") from e
        settings={k:json.loads(v) for k,v in c.execute(
            "SELECT key,value FROM settings WHERE key IN ('schema_version','persona')").fetchall()}
        root=_logical_root_conn(c)
        if not meta or meta[4]!=root:
            raise ArchiveQualificationError("archive logical-root mismatch")
        if app!=R13_APP_ID or meta[0]!=R13_FORMAT or int(meta[1])!=R13_ARCHIVE_VERSION:
            raise ArchiveQualificationError("wrong archive format")
        if not(uv==int(meta[2])==int(settings.get("schema_version") or 0)==SCHEMA_VERSION):
            raise ArchiveQualificationError("unsupported schema")
        expected_iid=str(meta[3] or "")
        if not expected_iid or expected_iid!=(settings.get("persona") or {}).get("id"):
            raise ArchiveQualificationError("identity mismatch")
    finally:
        c.close()
    return {"format":"single_sqlite","expected_identity_id":expected_iid,"source_schema_version":SCHEMA_VERSION,
            "logical_root":root}

def _setting(conn,key,default=None):
    row=conn.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
    return json.loads(row[0]) if row else default

def _growth_ids(value, label):
    if not isinstance(value,list):
        raise ArchiveQualificationError(label+" evidence must be a list")
    ids=[]
    for x in value:
        if isinstance(x,bool):
            raise ArchiveQualificationError(label+" evidence id invalid")
        try:
            n=int(x)
        except Exception as e:
            raise ArchiveQualificationError(label+" evidence id invalid") from e
        if n<=0:
            raise ArchiveQualificationError(label+" evidence id invalid")
        ids.append(n)
    if not (2<=len(ids)<=12) or len(set(ids))!=len(ids):
        raise ArchiveQualificationError(label+" evidence cardinality invalid")
    return ids

def _growth_event_admissible(kind, actor):
    # Mirror the current supported IdentityStore.propose_growth contract exactly:
    # confirmed growth evidence must resolve to real conversation./pet. events.
    # The authoritative write path does not impose an actor-kind pairing here.
    kind=str(kind)
    return kind.startswith(("conversation.","pet."))

def _growth_note_key(note, label):
    if not isinstance(note,dict):
        raise ArchiveQualificationError(label+" growth note invalid")
    text=str(note.get("text") or "").strip()
    if not text:
        raise ArchiveQualificationError(label+" growth text invalid")
    ids=_growth_ids(note.get("evidence_event_ids"),label)
    return text,tuple(ids)

def _validate_growth_provenance(conn, persona):
    events={}
    reflections=[]
    for row in conn.execute("SELECT event_id,kind,actor,content,extra FROM events ORDER BY event_id"):
        eid=int(row["event_id"])
        events[eid]=(str(row["kind"]),str(row["actor"]),str(row["content"]),str(row["extra"]))
        if str(row["kind"])=="reflection.accepted":
            if str(row["actor"])!="user":
                raise ArchiveQualificationError("accepted growth reflection actor invalid")
            try:
                extra=json.loads(row["extra"])
            except Exception as e:
                raise ArchiveQualificationError("accepted growth reflection extra invalid") from e
            ids=_growth_ids(extra.get("evidence") if isinstance(extra,dict) else None,
                            "accepted reflection")
            reflections.append((str(row["content"]).strip(),tuple(ids)))

    def validate_evidence(ids,label):
        for eid in ids:
            row=events.get(int(eid))
            if row is None:
                raise ArchiveQualificationError(label+" evidence event missing")
            kind,actor,_,_=row
            if not _growth_event_admissible(kind,actor):
                raise ArchiveQualificationError(label+" evidence authority/kind invalid")

    current_notes=persona.get("growth_notes") or []
    if not isinstance(current_notes,list):
        raise ArchiveQualificationError("persona growth_notes invalid")
    current_keys=[]
    for i,note in enumerate(current_notes):
        key=_growth_note_key(note,f"persona growth[{i}]")
        validate_evidence(key[1],f"persona growth[{i}]")
        current_keys.append(key)

    version_keys=[]
    for row in conn.execute(
        "SELECT version,persona_json,reason,evidence_json FROM persona_versions ORDER BY version"):
        if str(row["reason"])!="Approved growth reflection":
            continue
        try:
            vp=json.loads(row["persona_json"])
            evidence=json.loads(row["evidence_json"])
        except Exception as e:
            raise ArchiveQualificationError("approved growth version JSON invalid") from e
        notes=vp.get("growth_notes") if isinstance(vp,dict) else None
        if not isinstance(notes,list) or not notes:
            raise ArchiveQualificationError("approved growth version missing note")
        key=_growth_note_key(notes[-1],f"persona version {int(row['version'])}")
        ids=_growth_ids(evidence,f"persona version {int(row['version'])}")
        if tuple(ids)!=key[1]:
            raise ArchiveQualificationError("approved growth version evidence mismatch")
        validate_evidence(ids,f"persona version {int(row['version'])}")
        version_keys.append(key)

    # Current persona is exactly the supported write-path tail of approved versions.
    if current_keys!=version_keys[-120:]:
        raise ArchiveQualificationError("persona growth/version cross-consistency mismatch")

    # propose_growth(confirmed=True) creates one accepted reflection and one
    # Approved growth persona version in the same transaction. Preserve that
    # one-to-one sequence contract, including text and evidence IDs.
    if reflections!=version_keys:
        raise ArchiveQualificationError("growth reflection/version cross-consistency mismatch")

def _validate_sqlite_candidate(stage_home, expected_identity_id):
    # Opening only the isolated staging home preserves current V1/V2 migration
    # semantics while ensuring no migration can touch the final destination.
    store=IdentityStore(stage_home)
    try:
        verify=store.verify()
        if verify["integrity"]!="ok" or verify["identity_id"]!=expected_identity_id:
            raise ArchiveQualificationError("Restored identity invalid")

        c=store.conn
        fk=[tuple(x) for x in c.execute("PRAGMA foreign_key_check").fetchall()]
        if fk:
            raise ArchiveQualificationError("foreign key violation")

        schema=int(_setting(c,"schema_version",0) or 0)
        persona=_setting(c,"persona",None)
        if not isinstance(persona,dict) or persona.get("id")!=expected_identity_id:
            raise ArchiveQualificationError("persona identity invalid")

        # Existing write-path authority rules, applied once at the archive trust boundary.
        bad_memory=c.execute(
            """SELECT m.memory_id,m.source_event,e.kind,e.actor
               FROM memories m LEFT JOIN events e ON e.event_id=m.source_event
               WHERE m.category NOT IN ('bootstrap','legacy')
                 AND (m.source_event IS NULL OR e.event_id IS NULL OR e.actor!='user'
                      OR e.kind NOT IN ('conversation.user','memory.saved','memory.corrected'))
               LIMIT 1"""
        ).fetchone()
        if bad_memory is not None:
            raise ArchiveQualificationError("memory provenance invalid")

        bad_proposal=c.execute(
            """SELECT p.proposal_id,p.source_event,e.kind,e.actor
               FROM memory_proposals p LEFT JOIN events e ON e.event_id=p.source_event
               WHERE e.event_id IS NULL OR e.actor!='user' OR e.kind!='conversation.user'
               LIMIT 1"""
        ).fetchone()
        if bad_proposal is not None:
            raise ArchiveQualificationError("proposal provenance invalid")

        _validate_growth_provenance(c,persona)

        if schema>=3:
            cursor=int(_setting(c,"memory_change_seq",0) or 0)
            rowmax=int(c.execute("SELECT COALESCE(MAX(change_seq),0) FROM memories").fetchone()[0] or 0)
            if cursor<rowmax:
                raise ArchiveQualificationError("memory generation cursor rollback")

        header={k:persona.get(k) for k in ("name","identity_commitments","style","bond_description")}
        header_json=dump(header)
        if len(header_json)>PERSONA_SECTION_LIMIT:
            raise ArchiveQualificationError("persona context exceeds bounded serialization")
        if json.loads(header_json)!=header:
            raise ArchiveQualificationError("persona serialization invalid")

        # Check the exact current model-visible serialization contract, not a parallel renderer.
        ctx=store.identity_context("__archive_preactivation_probe__",memories_override=[])
        a="【身份档案】\n"; b="\n【经过确认的成长记录】"
        if a not in ctx or b not in ctx:
            raise ArchiveQualificationError("identity context markers missing")
        visible=ctx.split(a,1)[1].split(b,1)[0]
        try:
            decoded=json.loads(visible)
        except Exception as e:
            raise ArchiveQualificationError("model-visible persona JSON malformed") from e
        if decoded!=header or visible!=header_json:
            raise ArchiveQualificationError("model-visible persona serialization incomplete")

        return {"verify":verify,"schema_version":schema,"persona_chars":len(header_json),
                "memory_generation":int(_setting(c,"memory_change_seq",0) or 0)}
    finally:
        store.close()

def import_to_new_home(archive,new_home):
    archive=Path(archive); home=Path(new_home)
    if home.exists():
        raise FileExistsError("Import needs a new nonexistent directory")
    home.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix="."+home.name+".preactivate-",dir=str(home.parent)))
    activated=False
    try:
        identity_dir=stage/"identity"; identity_dir.mkdir()
        db_dest=identity_dir/"identity.sqlite3"
        kind=_detect(archive)
        decoded=_decode_legacy(archive,db_dest) if kind=="legacy_zip" else _decode_single(archive,db_dest)
        qualified=_validate_sqlite_candidate(stage,decoded["expected_identity_id"])
        if home.exists():
            raise FileExistsError("Import destination appeared during qualification")
        stage.replace(home)
        activated=True
        return {"home":home,"format":decoded["format"],"qualification":qualified}
    finally:
        if not activated and stage.exists():
            shutil.rmtree(stage,ignore_errors=True)
