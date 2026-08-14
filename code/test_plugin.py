"""RAG Plugin 单元测试"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

def test_config_load():
    from retriever import load_config
    cfg = load_config("config.yaml")
    assert cfg['retrieval']['strategy'] in ('hybrid', 'vector-only', 'entity-only')
    assert cfg['chromadb']['collection'] == 'wiki_docs'

def test_hybrid_retriever_import():
    from retriever import HybridRetriever
    assert HybridRetriever is not None

def test_guard_think_block():
    import rag_mcp_server
    cleaned, violations = rag_mcp_server.guard_response("<think>hello</think>答案是42")
    assert 'think_block_removed' in violations
    assert '<think>' not in cleaned

def test_guard_counter_question():
    import rag_mcp_server
    cleaned, violations = rag_mcp_server.guard_response("你想往哪个方向深入？答案是42")
    assert 'counter_question' in violations

def test_guard_suggest_manual():
    import rag_mcp_server
    cleaned, violations = rag_mcp_server.guard_response("建议你查阅B-8xxxx手册")
    assert 'suggest_manual' in violations

def test_guard_rtcp_confirm():
    import rag_mcp_server
    cleaned, violations = rag_mcp_server.guard_response("先确认下你说的RTCP是哪个，再答你")
    assert 'counter_question' in violations

def test_guard_normal_answer():
    import rag_mcp_server
    cleaned, violations = rag_mcp_server.guard_response("更换电机 [来源: B-83284EN]")
    assert len(violations) == 0

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
