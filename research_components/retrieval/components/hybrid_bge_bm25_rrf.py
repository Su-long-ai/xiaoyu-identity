# -*- coding: utf-8 -*-
from __future__ import annotations
import collections
import hashlib
import math
import os
import re
import sqlite3
from pathlib import Path
import numpy as np
import onnxruntime as ort

MODEL_SNAPSHOT = (
    Path.home()/".cache"/"huggingface"/"hub"/
    "models--qdrant--bge-small-en-v1.5-onnx-q"/"snapshots"/
    "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
)
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
RRF_K = 60
RRF_SOURCE_DEPTH = 100
BM25_SPEAKER_BOOST = 1.5
STOP = {
    "the","a","an","is","was","were","are","be","to","of","on","in","at","and",
    "or","what","when","where","who","which","how","did","does","do","has","have",
    "had","her","his","their","she","he","they","it","for","with","from","as","by",
    "about","into","that","this","these","those","during"
}

def _tokens(s):
    return [x for x in re.findall(r"[a-z0-9]+", str(s).casefold())
            if len(x) > 1 and x not in STOP]

_GPU_RUNTIME = None
_GPU_RUNTIME_LOCK = __import__("threading").Lock()
_ORT_RUNTIME = None
_ORT_RUNTIME_LOCK = __import__("threading").Lock()
_EMBED_MEM_CACHE = {}
_EMBED_MEM_LOCK = __import__("threading").Lock()

TORCH_MODEL_SNAPSHOT = (
    Path.home()/".cache"/"huggingface"/"hub"/
    "models--BAAI--bge-small-en-v1.5"/"snapshots"/
    "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
)
TORCH_MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
ONNX_MODEL_REVISION = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"

class LocalBGE:
    """BGE encoder with semantics-preserving cache and optional existing CUDA backend.

    No network/package installation is performed. CUDA mode uses the already-local
    BAAI/bge-small-en-v1.5 PyTorch snapshot and the caller's existing CUDA torch env.
    CPU fallback preserves the historical quantized ONNX implementation.
    """
    def __init__(self, model_snapshot=MODEL_SNAPSHOT):
        import hashlib
        import sqlite3
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS","1")
        os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS","1")
        self._hashlib=hashlib
        self._sqlite3=sqlite3
        requested=str(os.environ.get("XIAOYU_BGE_BACKEND","auto") or "auto").strip().lower()
        if requested not in {"auto","cuda","cpu"}:
            raise ValueError(f"invalid XIAOYU_BGE_BACKEND={requested!r}")
        self.requested_backend=requested
        self.cache_only=str(os.environ.get("XIAOYU_BGE_CACHE_ONLY","0") or "0").strip().lower() in {"1","true","yes","on"}
        self.backend="onnx_cpu"
        self.device="cpu"
        self._torch=None
        self._runtime=None

        cuda_error=None
        if self.cache_only:
            if requested=="cpu":
                self.backend="onnx_cpu"
                self.device="cpu-cache"
            else:
                self.backend="torch_cuda"
                self.device="cuda:0-cache"
        elif requested in {"auto","cuda"}:
            try:
                import torch
                if not torch.cuda.is_available():
                    raise RuntimeError("torch.cuda.is_available() is false")
                if not (TORCH_MODEL_SNAPSHOT/"model.safetensors").is_file():
                    raise FileNotFoundError(TORCH_MODEL_SNAPSHOT/"model.safetensors")
                self._runtime=self._get_gpu_runtime(torch)
                self._torch=torch
                self.backend="torch_cuda"
                self.device="cuda:0"
            except Exception as e:
                cuda_error=f"{type(e).__name__}: {e}"
                if requested=="cuda":
                    raise RuntimeError("CUDA_BGE_BACKEND_UNAVAILABLE: "+cuda_error) from e

        if self._runtime is None and not self.cache_only:
            self._runtime=self._get_ort_runtime(Path(model_snapshot))
            self.backend="onnx_cpu"
            self.device="cpu"

        self.cuda_fallback_reason=cuda_error
        self.implementation_id=(
            f"bge-small-en-v1.5:{TORCH_MODEL_REVISION}:torch-cuda-autocast-fp16-v1"
            if self.backend=="torch_cuda" else
            f"qdrant-bge-small-en-v1.5-onnx-q:{ONNX_MODEL_REVISION}:cpu-v1"
        )
        self.cache_path=str(os.environ.get("XIAOYU_BGE_DISK_CACHE","") or "").strip()
        self._db=None
        if self.cache_path:
            cp=Path(self.cache_path)
            cp.parent.mkdir(parents=True,exist_ok=True)
            self._db=sqlite3.connect(str(cp),timeout=60,check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("PRAGMA busy_timeout=60000")
            self._db.execute("PRAGMA temp_store=MEMORY")
            self._db.execute("PRAGMA mmap_size=1073741824")
            self._db.execute("PRAGMA cache_size=-131072")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS embeddings ("
                "cache_key TEXT PRIMARY KEY, dim INTEGER NOT NULL, vector BLOB NOT NULL)"
            )
            cols={str(r[1]) for r in self._db.execute("PRAGMA table_info(embeddings)").fetchall()}
            if "cache_key" in cols:
                self._db_key_column="cache_key"
            elif "key" in cols:
                self._db_key_column="key"
            else:
                raise RuntimeError("unsupported embeddings cache schema: "+repr(sorted(cols)))
            self._db.commit()

    @staticmethod
    def _get_gpu_runtime(torch):
        global _GPU_RUNTIME
        if _GPU_RUNTIME is not None:
            return _GPU_RUNTIME
        with _GPU_RUNTIME_LOCK:
            if _GPU_RUNTIME is not None:
                return _GPU_RUNTIME
            from transformers import AutoModel, AutoTokenizer
            try:
                from transformers.utils import logging as hf_logging
                hf_logging.set_verbosity_error()
                hf_logging.disable_progress_bar()
            except Exception:
                pass
            tokenizer=AutoTokenizer.from_pretrained(str(TORCH_MODEL_SNAPSHOT),local_files_only=True)
            model=AutoModel.from_pretrained(
                str(TORCH_MODEL_SNAPSHOT),local_files_only=True
            ).to("cuda").eval()
            try:
                torch.backends.cuda.matmul.allow_tf32=True
                torch.set_float32_matmul_precision("high")
            except Exception:
                pass
            _GPU_RUNTIME={"tokenizer":tokenizer,"model":model}
            return _GPU_RUNTIME

    @staticmethod
    def _get_ort_runtime(root):
        global _ORT_RUNTIME
        if _ORT_RUNTIME is not None:
            return _ORT_RUNTIME
        with _ORT_RUNTIME_LOCK:
            if _ORT_RUNTIME is not None:
                return _ORT_RUNTIME
            if not (root/"model_optimized.onnx").is_file():
                raise FileNotFoundError(root/"model_optimized.onnx")
            from transformers import AutoTokenizer
            tokenizer=AutoTokenizer.from_pretrained(str(root),local_files_only=True)
            opts=ort.SessionOptions()
            opts.intra_op_num_threads=max(1,min(8,os.cpu_count() or 4))
            session=ort.InferenceSession(
                str(root/"model_optimized.onnx"),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            _ORT_RUNTIME={
                "tokenizer":tokenizer,
                "session":session,
                "input_names":{i.name for i in session.get_inputs()},
            }
            return _ORT_RUNTIME

    def backend_info(self):
        return {
            "backend":self.backend,
            "device":self.device,
            "implementation_id":self.implementation_id,
            "requested_backend":self.requested_backend,
            "disk_cache":bool(self.cache_path),
            "cache_only":bool(self.cache_only),
            "cuda_fallback_reason":self.cuda_fallback_reason,
        }

    def _key(self,text,max_length,query):
        raw=(
            self.implementation_id+"\0"+("Q" if query else "D")+"\0"+
            str(int(max_length))+"\0"+str(text)
        ).encode("utf-8")
        return self._hashlib.sha256(raw).hexdigest()

    def _lookup(self,keys):
        found={}
        missing=[]
        with _EMBED_MEM_LOCK:
            for k in keys:
                v=_EMBED_MEM_CACHE.get(k)
                if v is None:
                    missing.append(k)
                else:
                    found[k]=v
        if self._db is not None and missing:
            for i in range(0,len(missing),8000):
                chunk=missing[i:i+8000]
                marks=",".join("?" for _ in chunk)
                col=self._db_key_column
                rows=self._db.execute(
                    f"SELECT {col},dim,vector FROM embeddings WHERE {col} IN ({marks})",
                    chunk,
                ).fetchall()
                with _EMBED_MEM_LOCK:
                    for k,dim,blob in rows:
                        arr=np.frombuffer(blob,dtype=np.float32,count=int(dim)).copy()
                        _EMBED_MEM_CACHE[k]=arr
                        found[k]=arr
        return found

    def _store(self,pairs):
        if not pairs:
            return
        with _EMBED_MEM_LOCK:
            for k,arr in pairs:
                _EMBED_MEM_CACHE[k]=np.asarray(arr,dtype=np.float32)
        if self._db is not None:
            rows=[
                (k,int(len(arr)),np.asarray(arr,dtype=np.float32).tobytes())
                for k,arr in pairs
            ]
            col=self._db_key_column
            self._db.executemany(
                f"INSERT OR IGNORE INTO embeddings({col},dim,vector) VALUES(?,?,?)",
                rows,
            )
            self._db.commit()

    def _encode_uncached_gpu(self,texts,batch_size,max_length):
        torch=self._torch
        tok=self._runtime["tokenizer"]
        model=self._runtime["model"]
        parts=[]
        i=0
        current=max(1,int(batch_size))
        while i<len(texts):
            batch=texts[i:i+current]
            try:
                enc=tok(
                    batch,padding=True,truncation=True,max_length=int(max_length),
                    return_tensors="pt",
                )
                enc={k:v.to("cuda",non_blocking=True) for k,v in enc.items()}
                with torch.inference_mode():
                    with torch.autocast(device_type="cuda",dtype=torch.float16):
                        arr=model(**enc).last_hidden_state[:,0,:]
                    arr=torch.nn.functional.normalize(arr.float(),p=2,dim=1)
                parts.append(arr.cpu().numpy().astype(np.float32,copy=False))
                i+=len(batch)
            except RuntimeError as e:
                if "out of memory" not in str(e).lower() or current<=1:
                    raise
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
                current=max(1,current//2)
        return np.concatenate(parts,axis=0) if parts else np.zeros((0,384),dtype=np.float32)

    def _encode_uncached_cpu(self,texts,batch_size,max_length):
        tok=self._runtime["tokenizer"]
        session=self._runtime["session"]
        input_names=self._runtime["input_names"]
        parts=[]
        for p in range(0,len(texts),max(1,int(batch_size))):
            enc=tok(
                texts[p:p+batch_size],
                padding=True,truncation=True,max_length=int(max_length),
                return_tensors="np",
            )
            feed={n:enc[n].astype(np.int64) for n in input_names if n in enc}
            arr=session.run(None,feed)[0][:,0,:].astype(np.float32)
            arr/=np.maximum(np.linalg.norm(arr,axis=1,keepdims=True),1e-12)
            parts.append(arr)
        return np.concatenate(parts,axis=0) if parts else np.zeros((0,384),dtype=np.float32)

    def encode(self,texts,batch_size=64,max_length=256,query=False):
        raw=[str(x) for x in texts]
        if not raw:
            return np.zeros((0,384),dtype=np.float32)
        effective=[(QUERY_PREFIX if query else "")+x for x in raw]
        keys=[self._key(x,max_length,query) for x in raw]
        found=self._lookup(keys)

        missing_by_key={}
        for k,t in zip(keys,effective):
            if k not in found and k not in missing_by_key:
                missing_by_key[k]=t
        if missing_by_key:
            if self.cache_only:
                raise RuntimeError(
                    f"BGE_CACHE_ONLY_MISS: {len(missing_by_key)} embedding(s) missing for {self.implementation_id}"
                )
            miss_keys=list(missing_by_key)
            miss_texts=[missing_by_key[k] for k in miss_keys]
            arr=(
                self._encode_uncached_gpu(miss_texts,batch_size,max_length)
                if self.backend=="torch_cuda" else
                self._encode_uncached_cpu(miss_texts,batch_size,max_length)
            )
            pairs=list(zip(miss_keys,arr))
            self._store(pairs)
            found.update({k:v for k,v in pairs})
        return np.stack([found[k] for k in keys],axis=0).astype(np.float32,copy=False)

    def prewarm(self,texts,batch_size=64,max_length=256,query=False):
        import time
        requested=[str(x) for x in texts]
        raw=list(dict.fromkeys(requested))
        keys=[self._key(x,max_length,query) for x in raw]
        started=time.time()
        found=self._lookup(keys)
        missing_by_key={}
        for k,t in zip(keys,raw):
            if k not in found and k not in missing_by_key:
                missing_by_key[k]=(QUERY_PREFIX if query else "")+t
        if missing_by_key:
            if self.cache_only:
                raise RuntimeError(
                    f"BGE_CACHE_ONLY_MISS: {len(missing_by_key)} embedding(s) missing for {self.implementation_id}"
                )
            miss_keys=list(missing_by_key)
            miss_texts=[missing_by_key[k] for k in miss_keys]
            arr=(
                self._encode_uncached_gpu(miss_texts,batch_size,max_length)
                if self.backend=="torch_cuda" else
                self._encode_uncached_cpu(miss_texts,batch_size,max_length)
            )
            self._store(list(zip(miss_keys,arr)))
        return {
            "requested":len(requested),
            "unique":len(raw),
            "cache_hits":len(found),
            "computed":len(missing_by_key),
            "elapsed_seconds":time.time()-started,
            "backend":self.backend,
            "device":self.device,
        }



def _bm25(documents, query, speaker_names=()):
    qtok = _tokens(query)
    n = len(documents)
    tokenized = [_tokens(d.get("text","")) for d in documents]
    df = collections.Counter()
    for ts in tokenized:
        for t in set(ts):
            df[t] += 1
    avg = sum(map(len, tokenized)) / max(1, n)
    targets = {
        str(x) for x in speaker_names
        if str(x) and str(x).casefold() in str(query).casefold()
    }
    scored = []
    for i,(d,ts) in enumerate(zip(documents, tokenized)):
        tf = collections.Counter(ts)
        length = max(1, len(ts))
        score = 0.0
        for t in set(qtok):
            if t not in tf:
                continue
            idf = math.log(1 + (n-df[t]+0.5)/(df[t]+0.5))
            f = tf[t]
            score += idf*(f*2.2)/(f + 1.2*(0.25 + 0.75*length/max(1,avg)))
        if targets and str(d.get("speaker") or "") in targets:
            score += BM25_SPEAKER_BOOST
        scored.append((score, i, str(d["id"])))
    scored.sort(key=lambda x:(-x[0], x[1], x[2]))
    return [i for _,i,_ in scored]

class HybridComponent:
    component_id = "hybrid_bge_bm25_rrf_v1"

    def __init__(self):
        self.model = LocalBGE()

    def prepare(self, documents):
        texts = [f"{d.get('speaker','')}: {d.get('text','')}" for d in documents]
        emb = self.model.encode(texts, batch_size=64, max_length=256, query=False)
        return {"documents": [dict(d) for d in documents], "embeddings": emb}

    def rank(self, query, *, state, limit=20, metadata=None):
        documents = state["documents"]
        if not documents or not str(query).strip():
            return []
        q = self.model.encode([str(query)], batch_size=1, max_length=128, query=True)[0]
        emb = np.asarray(state["embeddings"], dtype=np.float32)
        semantic = np.argsort(-(emb@q), kind="stable").tolist()
        lexical = _bm25(documents, query, (metadata or {}).get("speaker_names", ()))
        score = collections.Counter()
        for rank,i in enumerate(lexical[:RRF_SOURCE_DEPTH],1):
            score[int(i)] += 1.0/(RRF_K+rank)
        for rank,i in enumerate(semantic[:RRF_SOURCE_DEPTH],1):
            score[int(i)] += 1.0/(RRF_K+rank)
        order = [
            i for i,_ in sorted(
                score.items(),
                key=lambda kv:(-kv[1], str(documents[kv[0]]["id"]))
            )[:int(limit)]
        ]
        return [documents[i]["id"] for i in order]

def create_component():
    return HybridComponent()
