"""
simple_vectorstore.py — 纯 NumPy 向量存储（替代 ChromaDB）
零外部依赖，pickle 持久化，余弦相似度搜索
"""
import os
import pickle
import numpy as np
from typing import List, Optional, Tuple, Any, Dict
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings


class SimpleVectorStore:
    """轻量级向量存储，完全替代 ChromaDB"""

    def __init__(self, persist_path: str, embedding_function: Optional[Embeddings] = None):
        self.persist_path = persist_path
        self.embedding_function = embedding_function
        self._embeddings: Optional[np.ndarray] = None      # shape: (N, 1536)
        self._documents: List[str] = []                     # page_content
        self._metadatas: List[Dict[str, Any]] = []
        self._ids: List[str] = []

    # ────────────────────────────
    # 持久化
    # ────────────────────────────
    def save(self):
        os.makedirs(os.path.dirname(self.persist_path) or ".", exist_ok=True)
        data = {
            "embeddings": self._embeddings,
            "documents": self._documents,
            "metadatas": self._metadatas,
            "ids": self._ids,
        }
        with open(self.persist_path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

    def load(self) -> bool:
        if not os.path.exists(self.persist_path):
            return False
        with open(self.persist_path, "rb") as f:
            data = pickle.load(f)
        self._embeddings = data["embeddings"]
        self._documents = data["documents"]
        self._metadatas = data["metadatas"]
        self._ids = data["ids"]
        return True

    # ────────────────────────────
    # 构建向量库
    # ────────────────────────────
    @classmethod
    def from_documents(
        cls,
        documents: List[Document],
        embedding: Embeddings,
        persist_path: str,
    ) -> "SimpleVectorStore":
        store = cls(persist_path=persist_path, embedding_function=embedding)

        texts = [doc.page_content for doc in documents]
        store._documents = texts
        store._metadatas = [doc.metadata for doc in documents]
        store._ids = [f"chunk_{i}" for i in range(len(documents))]

        # 分批获取 embeddings（控制内存）
        print(f"[SimpleVS] Embedding {len(texts)} texts...")
        store._embeddings = np.array(embedding.embed_documents(texts), dtype=np.float32)
        print(f"[SimpleVS] Embeddings shape: {store._embeddings.shape}")

        store.save()
        return store

    def add_documents(self, documents: List[Document]) -> List[str]:
        texts = [doc.page_content for doc in documents]
        new_ids = [f"chunk_{len(self._ids) + i}" for i in range(len(documents))]
        new_embs = np.array(
            self.embedding_function.embed_documents(texts), dtype=np.float32
        )

        if self._embeddings is not None and len(self._embeddings) > 0:
            self._embeddings = np.vstack([self._embeddings, new_embs])
        else:
            self._embeddings = new_embs

        self._documents.extend(texts)
        self._metadatas.extend([doc.metadata for doc in documents])
        self._ids.extend(new_ids)
        self.save()
        return new_ids

    # ────────────────────────────
    # 搜索
    # ────────────────────────────
    def _normalize(self, vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec, axis=-1, keepdims=True)
        norm = np.maximum(norm, 1e-12)
        return vec / norm

    def similarity_search(
        self, query: str, k: int = 4, **kwargs
    ) -> List[Document]:
        return self.similarity_search_with_score(query, k, **kwargs)[0]

    def similarity_search_with_score(
        self, query: str, k: int = 4, **kwargs
    ) -> Tuple[List[Document], List[float]]:
        if self._embeddings is None or len(self._embeddings) == 0:
            return [], []

        # 向量化查询
        query_emb = np.array(
            self.embedding_function.embed_documents([query]), dtype=np.float32
        )

        # 余弦相似度（向量已归一化时等价于点积）
        db_norm = self._normalize(self._embeddings)
        q_norm = self._normalize(query_emb)
        scores = np.dot(db_norm, q_norm.T).flatten()

        # Top-K
        top_k = min(k, len(scores))
        idxs = np.argpartition(-scores, top_k - 1)[:top_k]
        idxs = idxs[np.argsort(-scores[idxs])]

        docs = [
            Document(page_content=self._documents[i], metadata=self._metadatas[i])
            for i in idxs
        ]
        score_list = [float(scores[i]) for i in idxs]
        return docs, score_list

    def as_retriever(self, search_kwargs: Optional[Dict] = None):
        """兼容 LangChain retriever 接口"""
        from langchain_core.retrievers import BaseRetriever

        search_kwargs = search_kwargs or {"k": 4}
        store = self

        class _Retriever(BaseRetriever):
            def _get_relevant_documents(self, query: str):
                return store.similarity_search(query, **search_kwargs)

        return _Retriever()

    # ────────────────────────────
    # 统计
    # ────────────────────────────
    def count(self) -> int:
        return len(self._ids) if self._ids else 0

    def get(self):
        return {
            "ids": self._ids,
            "documents": self._documents,
            "metadatas": self._metadatas,
        }
