# -*- coding: utf-8 -*-
from __future__ import annotations
import json,sqlite3,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge
from send_guard import capture_expectations,dual_guarded_chat
import model_adapter

ROOT=Path(__file__).resolve().parent

class Control:
    def __init__(self,status=200):
        self.status=status
        self.received=threading.Event()
        self.release=threading.Event()
        self.body=None

def start_server(control):
    class Handler(BaseHTTPRequestHandler):
        protocol_version="HTTP/1.1"
        def log_message(self,*args): pass
        def do_POST(self):
            n=int(self.headers.get("Content-Length","0"))
            control.body=self.rfile.read(n)
            control.received.set()
            control.release.wait(5)
            payload=json.dumps({
                "choices":[{"message":{"content":"OK"}}],"usage":{}
            }).encode("utf-8")
            self.send_response(control.status)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server

def config(server):
    return {
        "provider":"custom",
        "url":f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
        "model":"local-main06","key_env":"",
        # Synthetic localhost is explicitly trusted for this private-boundary
        # transport test. Production custom providers remain PUBLIC-only by
        # default unless policy grants a private data class.
        "allowed_data_classes":["PUBLIC","OWNER_PRIVATE"],
    }

def write_lock_available(path):
    con=sqlite3.connect(str(path),timeout=1.5)
    try:
        con.execute("PRAGMA busy_timeout=1500")
        con.execute("BEGIN IMMEDIATE")
        con.rollback()
        return True
    finally:
        con.close()

def one_success():
    with tempfile.TemporaryDirectory() as td:
        home=Path(td)
        store=IdentityStore(home)
        mid=store.add_memory("real http dispatch target",category="shared",priority=5)
        bridge=ProductMemoryBridge(home,store,component_root=ROOT)
        ctl=Control(200);server=start_server(ctl)
        out={}
        try:
            rows=bridge.recall("real http dispatch target",limit=7)
            gen=store.memory_generation()
            ex=capture_expectations(bridge,rows)
            def worker():
                try:
                    out["reply"]=dual_guarded_chat(
                        model_adapter.chat,config(server),
                        [{"role":"system","content":"real http dispatch target"}],
                        store.db_path,bridge.db_path,gen,ex,
                    )[0]
                except Exception as e:
                    out["error"]=type(e).__name__+":"+str(e)
            t=threading.Thread(target=worker);t.start()
            assert ctl.received.wait(3),"localhost did not receive POST body"
            assert t.is_alive(),"response should still be blocked"
            t0=time.perf_counter()
            assert write_lock_available(store.db_path)
            assert write_lock_available(bridge.db_path)
            lock_elapsed=time.perf_counter()-t0
            assert lock_elapsed<1.0,lock_elapsed
            ctl.release.set();t.join(3)
            assert not t.is_alive() and out.get("reply")=="OK" and "error" not in out,out
            body=json.loads(ctl.body.decode("utf-8"))
            assert body["model"]=="local-main06"
            return lock_elapsed
        finally:
            ctl.release.set();server.shutdown();server.server_close()
            bridge.close();store.close()

def one_http_error():
    with tempfile.TemporaryDirectory() as td:
        home=Path(td)
        store=IdentityStore(home)
        mid=store.add_memory("http error dispatch target",category="shared",priority=5)
        bridge=ProductMemoryBridge(home,store,component_root=ROOT)
        ctl=Control(402);ctl.release.set();server=start_server(ctl)
        try:
            rows=bridge.recall("http error dispatch target",limit=7)
            gen=store.memory_generation();ex=capture_expectations(bridge,rows)
            try:
                dual_guarded_chat(
                    model_adapter.chat,config(server),[],
                    store.db_path,bridge.db_path,gen,ex,
                )
            except RuntimeError as e:
                assert "402" in str(e),str(e)
            else:
                raise AssertionError("expected HTTP 402")
            assert write_lock_available(store.db_path)
            assert write_lock_available(bridge.db_path)
        finally:
            ctl.release.set();server.shutdown();server.server_close()
            bridge.close();store.close()

elapsed=one_success()
one_http_error()
print("PASS real_http_dispatch_releases_identity_and_r47_writers",round(elapsed,6))
print("PASS http_error_releases_identity_and_r47_writers")
print("SUMMARY 2 / 2 PASS")
