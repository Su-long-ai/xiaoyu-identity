# -*- coding: utf-8 -*-
"""Product adapter for the exact frozen V1 retrieval winner.

The GUI/product process may use a normal Python with Tk.  The frozen retrieval
component runs in a persistent CUDA worker using the exact audited Torch backend.
Authority remains owned by IdentityStore + accepted R47; the worker only ranks
an already-authorized document set.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

from research_components.retrieval import api as retrieval_api

WINNER_COMPONENT_ID = "novel_identity_path_v18_possessive"
AUDITED_IMPLEMENTATION_ID = (
    "bge-small-en-v1.5:5c38ec7c405ec4b44b94cc5a9bb96e735b38267a:"
    "torch-cuda-autocast-fp16-v1"
)
DEFAULT_GPU_PYTHON = Path(r"D:\cpod\venv_new\Scripts\python.exe")
EXPECTED = {
    "retrieval_component_v18.py":
        "70b5a1af7d5fe664f563bd3fc05099394b1852a962ee8916ce7f9cad4ab033be",
    "research_components/__init__.py":
        "94bd79075afe556ae282c2fd1c0fd952dac837695d21590c72901477693bca83",
    "research_components/retrieval/__init__.py":
        "a756a465a3a2b6e910807e1283f19e5af1807eb39c304652b632c48352999b9b",
    "research_components/retrieval/api.py":
        "47c05f73229e0d0b175a9f978279dcbd17e4f41d533add5fc3687c437b5c02e0",
    "research_components/retrieval/components/__init__.py":
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "research_components/retrieval/components/hybrid_bge_bm25_rrf.py":
        "51b5a20cb34e8dd463e06f6aeef84461b221ac18a5e52e13c87c9e24eec28297",
    "research_components/retrieval/components/multifacet_bge.py":
        "a315fc4e265109fb566863617428859e49ec03de52fe77af952a8cdc78fe8d35",
}


class ProductRetrievalError(RuntimeError):
    pass


class ProductRetrievalFreshnessChanged(ProductRetrievalError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _readline_timeout(stream, seconds: float) -> str:
    box = {}
    def run():
        try:
            box["line"] = stream.readline()
        except Exception as exc:
            box["error"] = exc
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(float(seconds))
    if t.is_alive():
        raise TimeoutError("retrieval_worker_response_timeout")
    if "error" in box:
        raise box["error"]
    return str(box.get("line") or "")


class V1CudaWorkerClient:
    START_TIMEOUT = 180
    REQUEST_TIMEOUT = 300

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        override = str(os.environ.get("XIAOYU_V1_RETRIEVAL_PYTHON") or "").strip()
        self.python = Path(override) if override else DEFAULT_GPU_PYTHON
        if not self.python.is_file():
            raise ProductRetrievalError(
                "audited_retrieval_python_missing:" + str(self.python)
            )
        worker = self.root / "v1_retrieval_cuda_worker.py"
        if not worker.is_file():
            raise ProductRetrievalError("retrieval_worker_missing")

        env = os.environ.copy()
        env["XIAOYU_BGE_BACKEND"] = "cuda"
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        env["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
        self.proc = subprocess.Popen(
            [str(self.python), str(worker), "--root", str(self.root)],
            cwd=str(self.root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        self.lock = threading.Lock()
        try:
            line = _readline_timeout(self.proc.stdout, self.START_TIMEOUT)
            if not line:
                raise ProductRetrievalError("retrieval_worker_closed_before_ready")
            ready = json.loads(line)
            if ready.get("status") != "READY":
                raise ProductRetrievalError(
                    "retrieval_worker_start_failed:" + str(ready.get("error"))
                )
            info = dict(ready.get("backend_info") or {})
            if (
                str(ready.get("component_id")) != WINNER_COMPONENT_ID
                or str(ready.get("component_sha256")) != EXPECTED["retrieval_component_v18.py"]
                or str(info.get("backend")) != "torch_cuda"
                or str(info.get("requested_backend")) != "cuda"
                or str(info.get("implementation_id")) != AUDITED_IMPLEMENTATION_ID
            ):
                raise ProductRetrievalError(
                    "audited_retrieval_worker_binding_mismatch:" + repr(ready)
                )
            self.info = ready
        except Exception:
            self.close()
            raise

    def _request(self, obj: dict) -> dict:
        with self.lock:
            if self.proc.poll() is not None:
                raise ProductRetrievalError("retrieval_worker_exited")
            try:
                self.proc.stdin.write(
                    json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
                self.proc.stdin.flush()
                line = _readline_timeout(self.proc.stdout, self.REQUEST_TIMEOUT)
                if not line:
                    raise ProductRetrievalError("retrieval_worker_pipe_closed")
                out = json.loads(line)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
                raise
            if out.get("status") != "OK":
                raise ProductRetrievalError(
                    "retrieval_worker_error:" + str(out.get("error"))
                )
            return out

    def prepare(self, documents: list[dict]) -> int:
        return int(self._request({"cmd": "prepare", "documents": documents})["prepared"])

    def rank(self, query: str, limit: int) -> list[str]:
        return [
            str(x) for x in self._request(
                {"cmd": "rank", "query": str(query), "limit": int(limit)}
            ).get("ids", [])
        ]

    def close(self):
        proc = getattr(self, "proc", None)
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin is not None and proc.stdout is not None:
                with getattr(self, "lock", threading.Lock()):
                    proc.stdin.write('{"cmd":"close"}\n')
                    proc.stdin.flush()
                    _readline_timeout(proc.stdout, 5)
        except Exception:
            pass
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            for stream in (getattr(proc, "stdin", None), getattr(proc, "stdout", None)):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass


class FrozenV1RetrievalAdapter:
    """Exact frozen ranking component behind deterministic authority fences."""

    MAX_BUILD_RETRIES = 3

    def __init__(self, component_root: str | Path):
        self.root = Path(component_root).resolve()
        self.worker = None
        self.worker_info = None
        self.documents = None
        self.authorized_index = None
        self.state = None
        self.cache_key = None
        self._verify_packaged_bytes()

    def _verify_packaged_bytes(self):
        for rel, expected in EXPECTED.items():
            p = self.root / rel
            if not p.is_file():
                raise ProductRetrievalError("retrieval_dependency_missing:" + rel)
            got = _sha(p)
            if got != expected:
                raise ProductRetrievalError(
                    "retrieval_dependency_hash_mismatch:" + rel + ":" + got
                )

    def _ensure_worker(self):
        if self.worker is None:
            self.worker = V1CudaWorkerClient(self.root)
            self.worker_info = dict(self.worker.info)
        return self.worker

    @staticmethod
    def _pragma_data_version(conn) -> int:
        return int(conn.execute("PRAGMA data_version").fetchone()[0])

    def version_key(self, bridge):
        """Fence same-connection and external commits in both durable stores."""
        iconn = bridge.identity_store.conn
        rconn = bridge.pipeline.store.db
        return (
            int(bridge.identity_store.memory_table_revision()),
            self._pragma_data_version(iconn),
            int(iconn.total_changes),
            self._pragma_data_version(rconn),
            int(rconn.total_changes),
        )

    def invalidate(self):
        self.documents = None
        self.authorized_index = None
        self.state = None
        self.cache_key = None

    def ensure_cache(self, bridge):
        worker = self._ensure_worker()
        current = self.version_key(bridge)
        if self.state is not None and current == self.cache_key:
            return self.cache_key

        self.invalidate()
        for _attempt in range(self.MAX_BUILD_RETRIES):
            bridge.sync()
            before = self.version_key(bridge)
            documents = retrieval_api.authorized_documents(bridge)
            after_materialize = self.version_key(bridge)
            if before != after_materialize:
                continue
            worker.prepare(documents)
            after_prepare = self.version_key(bridge)
            if after_materialize != after_prepare:
                continue
            self.documents = documents
            self.authorized_index = retrieval_api.authorized_document_index(documents)
            self.state = True
            self.cache_key = after_prepare
            return self.cache_key
        raise ProductRetrievalFreshnessChanged("retrieval_state_unstable_during_build")

    def rank_locked(self, bridge, query: str, limit: int):
        if self.state is None or self.cache_key is None:
            raise ProductRetrievalFreshnessChanged("retrieval_cache_missing")
        if not bridge.pipeline.store.db.in_transaction:
            raise ProductRetrievalFreshnessChanged("r47_lock_missing")

        before = self.version_key(bridge)
        if before != self.cache_key:
            raise ProductRetrievalFreshnessChanged("retrieval_cache_stale_before_rank")

        ranked_ids = self._ensure_worker().rank(str(query), int(limit))
        hits = []
        seen = set()
        for did in ranked_ids:
            if did in seen:
                continue
            seen.add(did)
            doc = self.authorized_index.get(str(did))
            if doc is None:
                raise ProductRetrievalError(
                    "retrieval_component_returned_unauthorized_id:" + str(did)
                )
            hits.append(doc)
            if len(hits) >= max(1, min(20, int(limit))):
                break

        after_rank = self.version_key(bridge)
        if after_rank != self.cache_key:
            raise ProductRetrievalFreshnessChanged("retrieval_cache_stale_after_rank")

        ids = [int(hit["memory_id"]) for hit in hits]
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        authoritative = {
            int(row["memory_id"]): dict(row)
            for row in bridge.identity_store.conn.execute(
                f"""SELECT memory_id,category,text,priority,status
                    FROM memories
                    WHERE status='active' AND memory_id IN ({marks})""",
                ids,
            )
        }
        authority = bridge._r47_authority_batch(ids, authoritative)

        out = []
        for hit in hits:
            mid = int(hit["memory_id"])
            row = authoritative.get(mid)
            allowed, _reason = authority.get(mid, (False, "authority_missing"))
            if (
                row is None
                or not allowed
                or str(row["category"]) != str(hit["category"])
                or str(row["text"]) != str(hit["text"])
            ):
                raise ProductRetrievalFreshnessChanged(
                    "retrieval_selected_memory_changed"
                )
            out.append({
                "memory_id": mid,
                "category": str(row["category"]),
                "text": str(row["text"]),
                "priority": int(row.get("priority") or hit.get("priority") or 3),
                "authority": "user_state",
                "source_id": bridge._external_id(mid),
                "retrieval": WINNER_COMPONENT_ID,
            })

        final_key = self.version_key(bridge)
        if final_key != self.cache_key:
            raise ProductRetrievalFreshnessChanged("retrieval_cache_stale_after_authority")
        return out

    def close(self):
        if self.worker is not None:
            try:
                self.worker.close()
            finally:
                self.worker = None
                self.worker_info = None
        self.invalidate()
