"""Shared config, embedding function, and Chroma helpers for issuestore.

The target GitHub repository is resolved (``owner/name``) in this order:
the ``ISSUE_REPO`` environment variable, else the GitHub ``origin`` remote of
the invoking directory's git repo (``INIT_CWD`` when set, else the process
cwd), else the ``holoviz/holoviews`` default. Raw issue JSON and the Chroma
vector store live in a per-repo subfolder
of the platformdirs user cache, so the same install works across many
repositories without colliding.
"""

from __future__ import annotations

import os
import re
import subprocess

# Enforce fully-offline model loading and quiet startup. Must be set before any
# huggingface/transformers import, so keep this at the top of the module.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
# Reduce CUDA fragmentation/OOM when the GPU is shared with other processes.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import functools

import chromadb
import platformdirs
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

APP_NAME = "issuestore"

_GITHUB_REMOTE_RE = re.compile(r"github\.com[:/](?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$")


def _slug_from_remote(url: str) -> str | None:
    m = _GITHUB_REMOTE_RE.search(url.strip())
    return m.group("slug") if m else None


def repo_from_git_remote() -> str | None:
    """Return the ``owner/name`` slug of the invoking dir's GitHub ``origin`` remote.

    Detection runs in ``INIT_CWD`` (the directory a task runner such as pixi/npm
    was launched from) when set, else the process cwd. This matters because pixi
    runs named tasks with cwd set to the manifest root, not where the user is;
    ``INIT_CWD`` still points at the repo checkout they invoked from.

    Returns ``None`` when not in a git repo, there is no ``origin`` remote, or
    the URL is not a recognizable GitHub remote.
    """
    cwd = os.environ.get("INIT_CWD") or None
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None
    if out.returncode != 0:
        return None
    return _slug_from_remote(out.stdout)


# Which GitHub repository this process operates on. Everything (cache paths,
# collection name) is derived from it. Prefer an explicit ISSUE_REPO override,
# then infer from the current git checkout's origin remote, then fall back.
REPO = os.environ.get("ISSUE_REPO") or repo_from_git_remote()
assert REPO in ("holoviz/holoviews", "holoviz/panel", "holoviz/hvplot")


def _repo_slug(repo: str) -> str:
    """Filesystem-safe per-repo key, e.g. 'holoviz/holoviews' -> 'holoviz__holoviews'."""
    return repo.replace("/", "__")


# Per-repo cache under the platformdirs user cache dir (e.g.
# ~/.cache/issuestore/holoviz__holoviews/{data,chroma_db}). Override the root with
# issuestore_CACHE_DIR if desired.
CACHE_ROOT = platformdirs.user_cache_dir(APP_NAME)
REPO_CACHE = os.path.join(CACHE_ROOT, _repo_slug(REPO))
DATA_DIR = os.path.join(REPO_CACHE, "data")
DB_DIR = os.path.join(REPO_CACHE, "chroma_db")


def data_dir_for(repo: str = REPO) -> str:
    """Raw ``issue-<n>.json`` cache dir for ``repo`` (defaults to the active REPO).

    Every repo gets its own ``<cache>/<slug>/data`` folder, so this resolves the
    location of the downloaded raw issue JSON for any repo without needing to
    re-set ``ISSUE_REPO``.
    """
    if repo == REPO:
        return DATA_DIR
    return os.path.join(CACHE_ROOT, _repo_slug(repo), "data")


COLLECTION = "issues"
MODEL_NAME = "BAAI/bge-large-en-v1.5"
UPSERT_BATCH = 256  # how many issues to hand to Chroma per upsert
ENCODE_BATCH = 32  # GPU forward-pass batch size (keeps VRAM bounded)
MAX_SEQ_LEN = 512  # bge-large context window

# bge models want an instruction prefix for retrieval-style queries. Passages
# (the stored documents) are embedded without a prefix.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class BGEEmbeddingFunction(EmbeddingFunction):
    """Chroma embedding function backed by sentence-transformers on the GPU."""

    def __init__(self, model_name: str = MODEL_NAME, device: str = "cuda") -> None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        self._model = SentenceTransformer(model_name, device=device)
        self._model.max_seq_length = MAX_SEQ_LEN
        self._name = model_name

    def name(self) -> str:  # required by newer chromadb for persistence metadata
        return f"bge:{self._name}"

    def __call__(self, input: Documents) -> Embeddings:
        embs = self._model.encode(
            list(input),
            batch_size=ENCODE_BATCH,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embs.tolist()

    # chromadb's base annotates a batched `Embeddings` return; we intentionally
    # expose a single query vector as list[float] for our own callers.
    def embed_query(self, text: str) -> list[float]:
        return self.embed_queries([text])[0]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        embs = self._model.encode(
            [QUERY_PREFIX + t for t in texts],
            batch_size=ENCODE_BATCH,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embs.tolist()


@functools.lru_cache(maxsize=1)
def get_embedder() -> BGEEmbeddingFunction:
    return BGEEmbeddingFunction()


def get_collection(create: bool = False):
    """Open the persistent Chroma collection with the shared embedding function."""
    if create:
        os.makedirs(DB_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=DB_DIR)
    if create:
        return client.get_or_create_collection(
            name=COLLECTION,
            embedding_function=get_embedder(),
            metadata={"hnsw:space": "cosine"},
        )
    return client.get_collection(name=COLLECTION, embedding_function=get_embedder())
