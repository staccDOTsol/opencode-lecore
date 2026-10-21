#!/usr/bin/env python3
"""Warm, local leCore memory worker. One JSON object in and out per line.

OpenCode owns message structure. This process archives exact textual payloads,
retrieves source-bearing evidence with leCore's measured lexical default, and
returns bounded replacements. It never invokes a model or changes tool IDs.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from collections import OrderedDict


SOURCE = Path(os.environ.get("LECORE_SOURCE", Path(__file__).resolve().parents[3] / "vendor" / "lecore")).resolve()
if not (SOURCE / "lecore.py").is_file():
    raise RuntimeError(f"leCore source unavailable at {SOURCE}; initialize vendor/lecore or set LECORE_SOURCE")
sys.path.insert(0, str(SOURCE))

from holographic.caching_and_storage.holographic_knowledgestore import KnowledgeStore
from holographic.caching_and_storage.holographic_perfectrecall import PerfectRecallIndex
from holographic.io_and_interop.holographic_container import load_container, save_container
from holographic.semantic_router.holographic_bm25 import BM25, tokenize
from holographic.semantic_router.holographic_recallguard import guard_candidates
from holographic.misc.holographic_determinism import topk_det


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def revision():
    pin = Path(__file__).resolve().parents[1] / "lecore.lock.json"
    if pin.is_file():
        data = json.loads(pin.read_text())
        return data.get("revision", data.get("commit", "unknown"))
    git = SOURCE / ".git"
    if git.is_dir() and (git / "HEAD").is_file():
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref: "):
            return head
        target = git / head[5:]
        if target.is_file():
            return target.read_text().strip()
    return "unknown"


ENGINE = {"name": "leCore", "revision": revision(), "retriever": "lecore.BM25+PerfectRecallIndex"}


@contextlib.contextmanager
def locked(path):
    """Serializes durable mutations across clients sharing this local partition."""
    with path.open("a+b") as handle:
        if os.name == "posix":
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(handle, fcntl.LOCK_UN)


class Partition:
    def __init__(self, root, workspace, session):
        self.workspace = str(Path(workspace).resolve())
        self.session = session
        self.scope = digest(self.workspace + "\0" + session)
        self.root = root / self.scope
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "originals.lecore"
        self.records = {}
        self.active = {}
        self.version = None
        self.index_key = None
        self.pool = []
        self.bm = None
        self.exact = None
        self.guard_cache = OrderedDict()
        self.store = None
        self.load()

    def load(self):
        version = self.path.stat().st_mtime_ns if self.path.exists() else 0
        if self.store is not None and self.version == version:
            return
        self.records = {}
        self.active = {}
        if version:
            contents = load_container(self.path.read_bytes())
            for section in contents["sections"]:
                if section["kind"] == "opencode.lecore.originals":
                    self.records = section["meta"]["records"]
                    self.active = section["meta"]["active"]
        self.store = KnowledgeStore(str(self.root), session=self.session)
        self.version = version
        self.index_key = None

    def save(self):
        # Journal first: a crash can leave an unused chunk, never a committed
        # original referring to a chunk that was not durably saved.
        self.store.save()
        payload = save_container([{
            "kind": "opencode.lecore.originals", "id": "v1", "arrays": {},
            "meta": {"records": self.records, "active": self.active},
        }], meta={"workspace": self.workspace, "session": self.session, "engine": ENGINE})
        temp = self.path.with_suffix(f".{os.getpid()}.tmp")
        with temp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)
        self.version = self.path.stat().st_mtime_ns

    def file_stamp(self, file_path):
        if not file_path:
            return None
        path = Path(file_path)
        if not path.is_absolute():
            path = Path(self.workspace) / path
        path = path.resolve()
        if not path.is_relative_to(Path(self.workspace)):
            raise ValueError("file_path must be within this workspace")
        if not path.is_file():
            return {"path": str(path), "missing": True}
        stat = path.stat()
        return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def stale(self, record):
        stamp = record.get("file_stamp")
        if not stamp:
            return False
        path = Path(stamp["path"])
        if not path.is_file():
            return True
        stat = path.stat()
        if stat.st_mtime_ns == stamp.get("mtime_ns") and stat.st_size == stamp.get("size"):
            return False
        # Touching a file does not invalidate its content; changed bytes do.
        return hashlib.sha256(path.read_bytes()).hexdigest() != stamp.get("sha256")

    def ingest(self, items):
        changed = 0
        if any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
               or not isinstance(item.get("text"), str) for item in items):
            raise ValueError("items must have string id and text")
        for item in items:
            if not item["id"] or not item["text"]:
                continue
            content_hash = digest(item["text"])
            key = digest(item["id"] + "\0" + content_hash)
            if self.active.get(item["id"]) == key:
                continue
            if key not in self.records:
                source = str(item.get("source") or item["id"])
                kind = str(item.get("kind") or "turn")
                knowledge_kind = "document" if kind in ("file", "document") else "output" if kind in ("assistant", "output") else "turn"
                # leCore's add is deduplicated. Preserve each input's ownership
                # in the originals section, rather than laundering a duplicate
                # into the first input's source citation.
                chunks = self.store.add(item["text"], kind=knowledge_kind,
                                        source=source, tags=("opencode",), save=False)
                self.records[key] = {"id": item["id"], "text": item["text"], "source": source,
                                     "kind": kind, "hash": content_hash, "chunks": chunks,
                                     "sequence": len(self.records) + 1,
                                     "file_stamp": self.file_stamp(item.get("file_path"))}
            self.active[item["id"]] = key
            changed += 1
        if changed:
            self.index_key = None
            self.save()
        return changed

    def index(self):
        active = [(item_id, self.records[key]) for item_id, key in sorted(self.active.items())]
        fresh = [(item_id, record) for item_id, record in active if not self.stale(record)]
        key = digest("\n".join(record["hash"] + item_id for item_id, record in fresh))
        if key == self.index_key:
            return len(active) - len(fresh), False
        chunk_rows = {entry["id"]: entry for entry in self.store.entries}
        self.pool = []
        # One chunk can belong to several source inputs. Rank it once, with all
        # owners attached so evidence can name the actual originating input.
        owners = {}
        for item_id, record in fresh:
            for chunk_id in record["chunks"]:
                owners.setdefault(chunk_id, []).append(record)
        for chunk_id in sorted(owners):
            chunk = chunk_rows.get(chunk_id)
            if not chunk:
                continue
            self.pool.append({"id": chunk_id, "text": chunk["text"], "owners": owners[chunk_id]})
        self.bm = BM25([row["text"] for row in self.pool])
        self.exact = PerfectRecallIndex()
        for tokens in self.bm.docs_tokens:
            self.exact.add({"token": tokens})
        self.index_key = key
        self.guard_cache.clear()
        return len(active) - len(fresh), True

    def recall(self, queries, budget, current_ids, compress_ids=None):
        stale_count, rebuilt = self.index()
        begin = time.perf_counter()
        ranks = {}
        term_union = set()
        positive = set()
        for query in queries:
            if not query.strip() or not self.pool:
                continue
            # Raw strings enter leCore's tokenizer once; token lists stay
            # canonical. Mixing repeated stemming changes exact containment.
            terms = tokenize(query)
            term_union.update(terms)
            scores = self.bm.scores(terms, expand=True)
            order = topk_det(scores, min(len(scores), 128))
            for rank, doc in enumerate(order):
                if float(scores[doc]) <= 0:
                    continue
                positive.add(int(doc))
                ranks[int(doc)] = ranks.get(int(doc), 0.0) + 1.0 / (60 + rank + 1)
        order = sorted(ranks, key=lambda doc: (-ranks[doc], doc))
        certificate = {"complete_down_to": None, "tier_sizes": {}, "added": 0}
        guard_cached = False
        # The exact guard is useful for short identifier queries. Long prose
        # has combinatorial tiers and is explicitly outside this contract.
        if order and 0 < len(term_union) <= 8 and self.exact is not None:
            cache_key = (tuple(sorted(term_union)), tuple(order[:32]))
            guard_cached = cache_key in self.guard_cache
            if not guard_cached:
                self.guard_cache[cache_key] = guard_candidates(order[:32], sorted(term_union), self.exact, budget=128)
            self.guard_cache.move_to_end(cache_key)
            while len(self.guard_cache) > 64:
                self.guard_cache.popitem(last=False)
            order, certificate = self.guard_cache[cache_key]
            order = [doc for doc in order if doc in positive or any(t in self.bm.docs_tokens[doc] for t in term_union)]
        evidence = []
        used = 0
        selected = set()
        for doc in order:
            row = self.pool[doc]
            # Prefer an owner absent after compaction, then an owner eligible
            # for compression. Current protected text is already visible.
            owners = sorted(row["owners"], key=lambda owner: (
                owner["id"] in current_ids, owner["id"] not in (compress_ids or set()), owner["id"]))
            owner = owners[0]
            if compress_ids is not None and owner["id"] in current_ids and owner["id"] not in compress_ids:
                continue
            header = f"[lecore source={owner['source']} item={owner['id']} chunk={row['id']}]\n"
            remaining = budget - used - len(header)
            if remaining < 80:
                break
            text = row["text"]
            truncated = len(text) > remaining
            if truncated:
                # Center the final capped span on a matching term rather than
                # clipping away a needle near the end of a chunk.
                lower = text.lower()
                hits = [lower.find(term) for term in term_union if lower.find(term) >= 0]
                middle = min(hits) if hits else 0
                start = max(0, min(len(text) - remaining, middle - remaining // 3))
                text = text[start:start + remaining]
            evidence.append({"id": row["id"], "item_id": owner["id"], "text": text,
                             "source": owner["source"], "kind": owner["kind"],
                             "sequence": owner.get("sequence", 0),
                             "header": header, "hash": owner["hash"], "truncated": truncated})
            selected.add(doc)
            used += len(header) + len(text)
        # A candidate certificate cannot certify the final token-limited
        # payload. Report both sizes and never call a truncated slice complete.
        return evidence, {"indexed_chunks": len(self.pool), "retrieved_chunks": len(evidence),
                          "evidence_chars": used, "candidate_chunks": len(order),
                          "coverage_complete": bool(order) and len(selected) == len(order)
                              and not any(e["truncated"] for e in evidence),
                          "candidate_certificate": certificate, "stale_items": stale_count,
                          "index_rebuilt": rebuilt, "guard_cached": guard_cached,
                          "retrieval_ms": round((time.perf_counter() - begin) * 1000, 3),
                          "no_match": not bool(order)}

    def process(self, request):
        with locked(self.root / "partition.lock"):
            self.load()
            if request.get("op") == "original":
                key = self.active.get(str(request.get("item_id") or ""))
                if request.get("hash"):
                    key = digest(str(request.get("item_id") or "") + "\0" + str(request["hash"]))
                record = self.records.get(key)
                if record is None:
                    raise ValueError("original item not found in this session/workspace")
                return {"original": record, "stale": self.stale(record), "engine": ENGINE}
            if request.get("op") != "index-recall":
                raise ValueError("op must be index-recall, original, or health")
            items = request.get("items") or []
            queries = request.get("queries") or []
            if not isinstance(items, list) or not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
                raise ValueError("items and string queries must be arrays")
            begin = time.perf_counter()
            changed = self.ingest(items)
            budget = max(0, min(256_000, int(request.get("budgetChars", 16_000))))
            current_ids = {item["id"] for item in items if item.get("id")}
            compress = request.get("compressIds")
            compress_ids = set(compress) if isinstance(compress, list) else None
            evidence, metrics = self.recall(queries, budget, current_ids, compress_ids)
            entries = []
            for item in items:
                if len(item["text"]) < 800 or (compress_ids is not None and item["id"] not in compress_ids):
                    continue
                marker = f"[lecore archived item={item['id']} sha256={digest(item['text'])[:16]}; exact original retained locally]"
                text = marker + "\n" + item["text"][:96] + "\n[…]\n" + item["text"][-96:]
                if len(text) < len(item["text"]):
                    entries.append({"id": item["id"], "text": text,
                                    "source": str(item.get("source") or item["id"]), "kind": item.get("kind", "turn")})
            metrics.update({"scope": self.scope, "archived_items": len(self.active), "new_items": changed,
                            "original_versions": len(self.records), "replacement_items": len(entries),
                            "input_chars": sum(len(item["text"]) for item in items),
                            "transform_ms": round((time.perf_counter() - begin) * 1000, 3)})
            return {"entries": entries, "evidence": evidence, "metrics": metrics, "engine": ENGINE}


class Worker:
    def __init__(self, root=None):
        state = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
        self.root = Path(root or os.environ.get("LECORE_STORAGE_DIR", str(Path(state) / "opencode" / "lecore"))).resolve()
        self.partitions = OrderedDict()

    def handle(self, request):
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        if request.get("op") == "health":
            return {"engine": ENGINE, "ready": True}
        workspace = request.get("workspace")
        session = request.get("session")
        if not isinstance(workspace, str) or not workspace or not isinstance(session, str) or not session:
            raise ValueError("workspace and session are required non-empty strings")
        key = (str(Path(workspace).resolve()), session)
        if key not in self.partitions:
            self.partitions[key] = Partition(self.root, *key)
        self.partitions.move_to_end(key)
        while len(self.partitions) > 8:
            self.partitions.popitem(last=False)
        try:
            return self.partitions[key].process(request)
        except Exception:
            # A rejected batch or interrupted durable write must not leave
            # speculative entries in the warm in-memory partition.
            self.partitions[key].store = None
            raise


def clean_text(value):
    """Replace unpaired UTF-16 surrogates (from tool output that was not valid UTF-8)
    with U+FFFD so every string can be hashed, stored and written as UTF-8."""
    if isinstance(value, str):
        return value.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
    if isinstance(value, list):
        return [clean_text(item) for item in value]
    if isinstance(value, dict):
        return {clean_text(key): clean_text(item) for key, item in value.items()}
    return value


def main():
    # Windows pipes default to the ANSI code page; the protocol is UTF-8 JSON lines.
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    worker = Worker()
    for line in sys.stdin:
        request = {}
        try:
            request = clean_text(json.loads(line))
            answer = {"id": request.get("id"), "ok": True, **worker.handle(request)}
        except Exception as error:
            answer = {"id": request.get("id") if isinstance(request, dict) else None,
                      "ok": False, "error": f"{type(error).__name__}: {error}"}
        print(json.dumps(clean_text(answer), ensure_ascii=False, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
