"""端到端煙霧測試:行內 config 全離線跑完 ingest → query。

一次驗證:方法鏈、mock embedding、hybrid 檢索、LLM 拆解(腳本)、
InsertRank 重排(腳本)、fusion 按文件聚合、mock 生成與 prompt 可稽核性。
"""

from __future__ import annotations

from rag.builder import build_pipelines
from rag.config import parse_config

SMOKE_CONFIG = {
    "ingestion": {
        "import": {
            "method": "local_file",
            "method_params": {
                "local_file": {
                    "input_dir": "./data/raw",  # 測試中覆寫為 corpus_dir
                    "extensions": [".txt", ".md"],
                }
            },
        },
        "parsing": {"method": ["plain_text", "clean"]},  # 方法鏈:轉換後清理
        "chunking": {
            "method": "fixed_size",
            "method_params": {
                "fixed_size": {"split_length": 120, "split_overlap": 20}
            },
        },
        "embedding": {"method": "mock", "method_params": {"mock": {"dim": 32}}},
        "indexing": {"method": "in_memory"},
    },
    "inference": {
        "query_transformation": {
            "method": ["normalize", "llm_decompose"],
            "method_params": {
                "normalize": {"lowercase": True},
                "llm_decompose": {
                    "max_subqueries": 3,
                    "generator": {  # 拆解用 mock LLM(腳本化輸出兩個子查詢)
                        "method": "mock",
                        "params": {
                            "replies": [
                                "1. FAISS 支援哪些索引結構?\n"
                                "2. Elasticsearch 提供哪些檢索能力?"
                            ]
                        },
                    },
                },
            },
        },
        "retrieval": {
            "method": "hybrid",  # BM25 + 向量,RRF 融合
            "method_params": {"hybrid": {"top_k": 4}},
        },
        "reranking": {
            "method": "insertrank",  # InsertRank + mock LLM(腳本化回傳排序)
            "method_params": {
                "insertrank": {
                    "top_k": 4,
                    "generator": {
                        "method": "mock",
                        "params": {"replies": ['{"ranking": [1, 2]}']},
                    },
                }
            },
        },
        "generation": {"method": "mock"},
        "fusion": {"group_by": "doc", "strategy": "rrf", "top_k": 3},
    },
}


def test_smoke_config_full_run(corpus_dir):
    data = SMOKE_CONFIG.copy()
    config = parse_config(data)
    config.ingestion.import_.method_params["local_file"]["input_dir"] = str(corpus_dir)

    pipelines = build_pipelines(config)
    ingestion_result = pipelines.run_ingestion()
    assert ingestion_result["writer"]["documents_written"] > 0

    result = pipelines.query("ＦＡＩＳＳ 與 Elasticsearch 各支援什麼檢索?")

    # 拆解:mock 腳本固定回兩個子查詢,各自獨立檢索與重排
    assert len(result["subquery_results"]) == 2
    for subquery_docs in result["subquery_results"]:
        assert subquery_docs, "每個子查詢都應有(重排後的)結果"

    # fusion:group_by doc → group_key 是 doc_id,帶聚合診斷 metadata
    documents = result["documents"]
    assert 0 < len(documents) <= 3
    for doc in documents:
        assert doc.meta["group_key"] in {"faiss.txt", "sub/es.txt"}
        assert doc.meta["num_merged"] >= 1
        assert doc.meta["sources"][0]["rank"] >= 1
    assert [d.score for d in documents] == sorted(
        (d.score for d in documents), reverse=True
    ), "融合結果必須降冪"

    # prompt 可稽核:含 [chunk_id] 前綴與原始問題
    assert "::chunk_" in result["prompt"]
    assert "ＦＡＩＳＳ 與 Elasticsearch 各支援什麼檢索?" in result["prompt"]

    # mock 生成:可辨識的假答案,meta 帶模型資訊
    assert result["answer"].startswith("[mock 回答]")
    assert result["reply_meta"]["model"] == "mock"
