# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse,json,math,pickle,struct,sys
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F

HIDDEN=384
HEADS=12
HEAD_DIM=32
LAYERS=12
EPS=1e-12

def read_exact(stream,n):
    parts=[];left=n
    while left:
        b=stream.read(left)
        if not b:raise EOFError
        parts.append(b);left-=len(b)
    return b"".join(parts)

def recv():
    n=struct.unpack("<Q",read_exact(sys.stdin.buffer,8))[0]
    return pickle.loads(read_exact(sys.stdin.buffer,n))

def send(obj):
    data=pickle.dumps(obj,protocol=4)
    sys.stdout.buffer.write(struct.pack("<Q",len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()

class BertGPU:
    def __init__(self,meta_path,device="cuda"):
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable in GPU worker")
        self.device=torch.device(device)
        meta=json.loads(Path(meta_path).read_text(encoding="utf-8"))
        bin_path=Path(meta["bin_path"])
        # One host->GPU transfer for the whole 133MB weight slab, then cheap GPU views.
        mm=np.memmap(bin_path,dtype=np.float32,mode="c")
        flat_cpu=torch.from_numpy(np.asarray(mm))
        self._flat=flat_cpu.to(self.device,dtype=torch.float32)
        self.w={}
        for k,spec in meta["tensors"].items():
            start=int(spec["offset_bytes"])//4
            count=int(spec["numel"])
            shape=tuple(int(x) for x in spec["shape"])
            self.w[k]=self._flat.narrow(0,start,count).view(*shape)
        self._mm=mm
        torch.backends.cuda.matmul.allow_tf32=False
        torch.backends.cudnn.allow_tf32=False

    def ln(self,x,prefix):
        return F.layer_norm(x,(HIDDEN,),self.w[prefix+".weight"],self.w[prefix+".bias"],EPS)

    @torch.inference_mode()
    def embed(self,input_ids,attention_mask,token_type_ids):
        ids=torch.from_numpy(np.asarray(input_ids,dtype=np.int64)).to(self.device)
        mask=torch.from_numpy(np.asarray(attention_mask,dtype=np.int64)).to(self.device)
        typ=torch.from_numpy(np.asarray(token_type_ids,dtype=np.int64)).to(self.device)
        b,s=ids.shape
        pos=torch.arange(s,device=self.device,dtype=torch.long).unsqueeze(0).expand(b,s)
        x=F.embedding(ids,self.w["embeddings.word_embeddings.weight"])
        x=x+F.embedding(pos,self.w["embeddings.position_embeddings.weight"])
        x=x+F.embedding(typ,self.w["embeddings.token_type_embeddings.weight"])
        x=self.ln(x,"embeddings.LayerNorm")
        key_mask=(mask[:,None,None,:]==0)
        scale=1.0/math.sqrt(HEAD_DIM)
        for i in range(LAYERS):
            p=f"encoder.layer.{i}"
            q=F.linear(x,self.w[p+".attention.self.query.weight"],self.w[p+".attention.self.query.bias"])
            k=F.linear(x,self.w[p+".attention.self.key.weight"],self.w[p+".attention.self.key.bias"])
            v=F.linear(x,self.w[p+".attention.self.value.weight"],self.w[p+".attention.self.value.bias"])
            q=q.view(b,s,HEADS,HEAD_DIM).transpose(1,2)
            k=k.view(b,s,HEADS,HEAD_DIM).transpose(1,2)
            v=v.view(b,s,HEADS,HEAD_DIM).transpose(1,2)
            scores=torch.matmul(q,k.transpose(-1,-2))*scale
            scores=scores.masked_fill(key_mask,-10000.0)
            probs=torch.softmax(scores,dim=-1)
            ctx=torch.matmul(probs,v).transpose(1,2).contiguous().view(b,s,HIDDEN)
            ao=F.linear(ctx,self.w[p+".attention.output.dense.weight"],self.w[p+".attention.output.dense.bias"])
            ao=self.ln(ao+x,p+".attention.output.LayerNorm")
            inter=F.gelu(
                F.linear(ao,self.w[p+".intermediate.dense.weight"],self.w[p+".intermediate.dense.bias"]),
                approximate="none",
            )
            out=F.linear(inter,self.w[p+".output.dense.weight"],self.w[p+".output.dense.bias"])
            x=self.ln(out+ao,p+".output.LayerNorm")
        cls=F.normalize(x[:,0,:],p=2,dim=1)
        return cls.detach().cpu().numpy().astype(np.float32,copy=False)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--weights-meta",required=True)
    args=ap.parse_args()
    model=BertGPU(args.weights_meta)
    send({"status":"READY","cuda":True,"device":torch.cuda.get_device_name(0),"torch":torch.__version__})
    while True:
        try:req=recv()
        except EOFError:break
        if req.get("cmd")=="close":
            send({"status":"BYE"});break
        if req.get("cmd")!="embed":
            send({"status":"ERROR","error":"unknown cmd"});continue
        try:
            arr=model.embed(req["input_ids"],req["attention_mask"],req["token_type_ids"])
            send({"status":"OK","embeddings":arr})
        except Exception as e:
            send({"status":"ERROR","error":repr(e)})

if __name__=="__main__":
    main()
