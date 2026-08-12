"""RAG Plugin — 抽象检索接口"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Optional
import yaml

class BaseRetriever(ABC):
    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        pass

class ChromaDBRetriever(BaseRetriever):
    def __init__(self, path: str, collection: str):
        import chromadb
        self.client = chromadb.PersistentClient(path=Path(path).expanduser())
        self.coll = self.client.get_collection(collection)
    
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        r = self.coll.query(query_texts=[query], n_results=top_k, include=["documents","metadatas","distances"])
        results = []
        for i in range(len(r['ids'][0])):
            dist = r.get('distances',[[]])[0][i] if r.get('distances') else None
            score = 1.0 - dist if dist is not None else 0.5
            results.append({
                'source': r['metadatas'][0][i].get('source',''),
                'text': r['documents'][0][i][:600],
                'method': 'chromadb',
                'score': round(float(score), 4),
            })
        return results

class SAGRetriever(BaseRetriever):
    def __init__(self, db_path: str):
        import sys; sys.path.insert(0, str(Path(db_path).parent))
        from sag_hybrid import hybrid_search
        self._search = hybrid_search
    
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        return self._search(query, top_k)

class HybridRetriever(BaseRetriever):
    def __init__(self, config: dict):
        self.sag = SAGRetriever(config['sag']['db_path'])
        self.chromadb = ChromaDBRetriever(config['chromadb']['path'], config['chromadb']['collection'])
    
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        sag_results = self.sag.retrieve(query, top_k=6)
        # entity-exact 优先
        seen = set()
        merged = []
        for r in sag_results:
            if r.get('method') == 'entity-exact' and r['source'] not in seen:
                seen.add(r['source']); merged.append(r)
        for r in sag_results:
            if r.get('method') == 'entity-hop' and r['source'] not in seen:
                seen.add(r['source']); merged.append(r)
        # 向量兜底
        if len(merged) < top_k:
            vec = self.chromadb.retrieve(query, top_k - len(merged))
            for r in vec:
                if r['source'] not in seen:
                    seen.add(r['source']); merged.append(r)
        return merged[:top_k]

def load_config(path: str = None) -> dict:
    if path is None:
        path = Path(__file__).parent / "config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)

def get_retriever(config: dict = None) -> BaseRetriever:
    if config is None:
        config = load_config()
    strategy = config['retrieval']['strategy']
    if strategy == 'hybrid':
        return HybridRetriever(config)
    elif strategy == 'vector-only':
        return ChromaDBRetriever(config['chromadb']['path'], config['chromadb']['collection'])
    elif strategy == 'entity-only':
        return SAGRetriever(config['sag']['db_path'])
    return HybridRetriever(config)
