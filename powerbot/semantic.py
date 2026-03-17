"""Semantic search (SentenceTransformers + FAISS).

Purpose
- Answer questions even when they don't contain an exact trigger substring.

This module is **optional**. If `sentence_transformers` or `faiss` isn't installed,
`build_index` and `query_index` return safe fallbacks.

Files
- data/semantic/index.faiss
- data/semantic/meta.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SemanticHit:
    score: float
    meta: Dict[str, Any]


DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Simple in-process caches to avoid re-loading models and FAISS index on every query.
# Safe for long-running bots; cache invalidates automatically when index files change.
_MODEL_CACHE: Dict[str, Any] = {}
_INDEX_CACHE: Dict[str, Dict[str, Any]] = {}

def _get_model(name: str, SentenceTransformer: Any) -> Any:
    m = _MODEL_CACHE.get(name)
    if m is None:
        m = SentenceTransformer(name)
        _MODEL_CACHE[name] = m
    return m

def _get_index(index_dir: str, *, faiss: Any) -> Tuple[Optional[Any], List[Dict[str, Any]], Optional[str]]:
    """
    Returns (faiss_index, docs, model_name). Uses file mtime-based cache invalidation.
    """
    idx_dir = Path(index_dir)
    idx_path = idx_dir / "index.faiss"
    meta_path = idx_dir / "meta.json"
    if not idx_path.exists() or not meta_path.exists():
        return None, [], None

    try:
        idx_mtime = idx_path.stat().st_mtime
        meta_mtime = meta_path.stat().st_mtime
    except Exception:
        idx_mtime = 0.0
        meta_mtime = 0.0

    cache = _INDEX_CACHE.get(index_dir)
    if cache and cache.get("idx_mtime") == idx_mtime and cache.get("meta_mtime") == meta_mtime:
        return cache.get("index"), cache.get("docs") or [], cache.get("model")

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        docs = meta.get("docs") or []
        model_name = meta.get("model")
        index = faiss.read_index(str(idx_path))
    except Exception:
        return None, [], None

    _INDEX_CACHE[index_dir] = {
        "idx_mtime": idx_mtime,
        "meta_mtime": meta_mtime,
        "index": index,
        "docs": docs,
        "model": model_name,
    }
    return index, docs, model_name

def _invalidate_index_cache(index_dir: str) -> None:
    _INDEX_CACHE.pop(index_dir, None)


def _try_import() -> Tuple[Optional[object], Optional[object]]:
    """Return (SentenceTransformer, faiss) or (None, None)."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception:
        SentenceTransformer = None
    try:
        import faiss  # type: ignore
    except Exception:
        faiss = None
    return SentenceTransformer, faiss


def _rules_to_documents(qa_rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for rule in qa_rules:
        if not isinstance(rule, dict):
            continue
        ans = rule.get("answer") or rule.get("response")
        if not isinstance(ans, str) or not ans.strip():
            continue
        triggers = rule.get("match_any") or rule.get("triggers") or []
        if not isinstance(triggers, list):
            triggers = []
        trigger_text = " | ".join(str(t) for t in triggers if str(t).strip())
        # Text we embed: triggers + a compact answer hint.
        text = f"{trigger_text}\n{ans}" if trigger_text else ans
        docs.append(
            {
                "text": text,
                "answer": ans,
                "rule_id": rule.get("id"),
                "scope": rule.get("scope"),
                "triggers": triggers,
            }
        )
    return docs


def build_index(
    *,
    qa_rules: List[Dict[str, Any]],
    out_dir: str,
    model_name: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """Build a FAISS index from QA rules.

    Returns a small status dict; never raises.
    """
    SentenceTransformer, faiss = _try_import()
    if SentenceTransformer is None or faiss is None:
        return {"ok": False, "reason": "missing_deps"}

    try:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        docs = _rules_to_documents(qa_rules)
        if not docs:
            return {"ok": False, "reason": "no_documents"}

        model = SentenceTransformer(model_name)
        texts = [d["text"] for d in docs]
        emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

        dim = int(emb.shape[1])
        index = faiss.IndexFlatIP(dim)
        index.add(emb.astype("float32"))

        faiss.write_index(index, str(out / "index.faiss"))
        with open(out / "meta.json", "w", encoding="utf-8") as f:
            json.dump({"model": model_name, "count": len(docs), "docs": docs}, f, indent=2, ensure_ascii=False)

        return {"ok": True, "count": len(docs), "model": model_name, "dim": dim}
    except Exception as e:
        return {"ok": False, "reason": f"error: {e}"}


def query_index(
    *,
    question: str,
    index_dir: str,
    k: int = 3,
    min_score: float = 0.33,
    model_name_fallback: str = DEFAULT_MODEL,
) -> List[SemanticHit]:
    """Query an existing index; returns hits sorted by score."""
    SentenceTransformer, faiss = _try_import()
    if SentenceTransformer is None or faiss is None:
        return []

    try:
        idx_dir = Path(index_dir)
        idx_path = idx_dir / "index.faiss"
        meta_path = idx_dir / "meta.json"
        if not idx_path.exists() or not meta_path.exists():
            return []

        index, docs, model_name = _get_index(index_dir, faiss=faiss)
        if index is None:
            return []
        model_name = (model_name or model_name_fallback)

        model = _get_model(model_name, SentenceTransformer)
        qv = model.encode([question], normalize_embeddings=True, show_progress_bar=False)

        scores, ids = index.search(qv.astype("float32"), int(k))

        hits: List[SemanticHit] = []
        for score, i in zip(scores[0], ids[0]):
            if i < 0 or i >= len(docs):
                continue
            if float(score) < float(min_score):
                continue
            hits.append(SemanticHit(score=float(score), meta=docs[int(i)]))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits
    except Exception:
        return []
