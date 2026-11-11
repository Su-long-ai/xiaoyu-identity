# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib,json,os,pickle,struct,subprocess,threading
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
CACHE=ROOT/"governance/evaluation/external_suite/cache"
NATIVE_SNAPSHOT=(
    Path.home()/".cache"/"huggingface"/"hub"/
    "models--BAAI--bge-small-en-v1.5"/"snapshots"/
    "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
)
WEIGHTS_BIN=CACHE/"bge_small_en_v1_5_float32_weights.bin"
WEIGHTS_META=CACHE/"bge_small_en_v1_5_float32_weights.meta.json"
WORKER=Path(__file__).with_name("bge_torch_cuda_worker.py")
GPU_PYTHONS=[
    Path.home()/".conda"/"envs"/"deeplearning_"/"python.exe",
    Path.home()/".conda"/"envs"/"deeplearning"/"python.exe",
]
_LOCK=threading.Lock()
_SHARED=None

def sha_file(p:Path):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def ensure_weights():
    src=NATIVE_SNAPSHOT/"model.safetensors"
    if not src.is_file():
        raise FileNotFoundError(src)
    CACHE.mkdir(parents=True,exist_ok=True)
    source_sha=sha_file(src)
    if WEIGHTS_BIN.is_file() and WEIGHTS_META.is_file():
        try:
            m=json.loads(WEIGHTS_META.read_text(encoding="utf-8"))
            if (
                m.get("schema")=="xiaoyu-bge-gpu-flat-weight-cache-v1"
                and m.get("source_sha256")==source_sha
                and int(m.get("bin_size") or -1)==WEIGHTS_BIN.stat().st_size
            ):
                return WEIGHTS_META
        except Exception:
            pass

    from safetensors import safe_open
    tmp=WEIGHTS_BIN.with_suffix(".tmp.bin")
    tensors={}
    offset=0
    h=hashlib.sha256()
    with open(tmp,"wb") as out, safe_open(src,framework="np") as f:
        for k in f.keys():
            if k=="embeddings.position_ids" or k.startswith("pooler."):
                continue
            a=f.get_tensor(k)
            if getattr(a,"dtype",None) is None or a.dtype.kind!="f":
                continue
            a=np.asarray(a,dtype=np.float32,order="C")
            raw=a.tobytes(order="C")
            out.write(raw);h.update(raw)
            tensors[k]={
                "offset_bytes":offset,
                "nbytes":len(raw),
                "numel":int(a.size),
                "shape":[int(x) for x in a.shape],
            }
            offset+=len(raw)
    os.replace(tmp,WEIGHTS_BIN)
    meta={
        "schema":"xiaoyu-bge-gpu-flat-weight-cache-v1",
        "source":str(src),
        "source_sha256":source_sha,
        "bin_path":str(WEIGHTS_BIN),
        "bin_sha256":h.hexdigest(),
        "bin_size":WEIGHTS_BIN.stat().st_size,
        "tensor_count":len(tensors),
        "tensors":tensors,
    }
    WEIGHTS_META.write_text(json.dumps(meta,indent=2)+"\n",encoding="utf-8")
    return WEIGHTS_META

def _read_exact(stream,n):
    parts=[];left=n
    while left:
        b=stream.read(left)
        if not b:raise EOFError("GPU worker pipe closed")
        parts.append(b);left-=len(b)
    return b"".join(parts)

def _recv(stream):
    n=struct.unpack("<Q",_read_exact(stream,8))[0]
    return pickle.loads(_read_exact(stream,n))

def _send(stream,obj):
    data=pickle.dumps(obj,protocol=4)
    stream.write(struct.pack("<Q",len(data)))
    stream.write(data)
    stream.flush()

def find_gpu_python():
    override=os.environ.get("XIAOYU_BGE_GPU_PYTHON")
    candidates=([Path(override)] if override else [])+GPU_PYTHONS
    for p in candidates:
        if not p.is_file():
            continue
        probe=subprocess.run(
            [str(p),"-c","import torch,numpy; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"],
            text=True,capture_output=True,timeout=20,
        )
        if probe.returncode==0:
            return p,probe.stdout.strip()
    raise RuntimeError("No existing CUDA Torch Python environment found")

class CudaBGEClient:
    def __init__(self):
        meta=ensure_weights()
        py,device=find_gpu_python()
        self.python=py
        self.device=device
        self.proc=subprocess.Popen(
            [str(py),str(WORKER),"--weights-meta",str(meta)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,
        )
        ready=_recv(self.proc.stdout)
        if ready.get("status")!="READY":
            raise RuntimeError("GPU worker failed to start: "+repr(ready))
        self.info=ready
        self.lock=threading.Lock()

    def embed(self,input_ids,attention_mask,token_type_ids):
        with self.lock:
            if self.proc.poll() is not None:
                raise RuntimeError("GPU worker exited")
            _send(self.proc.stdin,{
                "cmd":"embed",
                "input_ids":np.asarray(input_ids,dtype=np.int64),
                "attention_mask":np.asarray(attention_mask,dtype=np.int64),
                "token_type_ids":np.asarray(token_type_ids,dtype=np.int64),
            })
            out=_recv(self.proc.stdout)
            if out.get("status")!="OK":
                raise RuntimeError("GPU worker embed failed: "+str(out.get("error")))
            return np.asarray(out["embeddings"],dtype=np.float32)

    def close(self):
        try:
            if self.proc.poll() is None:
                _send(self.proc.stdin,{"cmd":"close"})
                _recv(self.proc.stdout)
        except Exception:
            pass
        try:self.proc.terminate()
        except Exception:pass

def get_shared_cuda_client():
    global _SHARED
    with _LOCK:
        if _SHARED is None:
            _SHARED=CudaBGEClient()
        return _SHARED

def cuda_backend_available():
    try:
        py,device=find_gpu_python()
        return True,{"python":str(py),"device":device}
    except Exception as e:
        return False,{"error":str(e)}
