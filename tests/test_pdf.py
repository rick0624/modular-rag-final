"""PdfToDocument(pypdf 文字層)與空來源回報的測試。"""

from __future__ import annotations

import logging

from conftest import make_config, minimal_two_page_pdf

from rag.builder import build_pipelines
from rag.components.pdf import PdfToDocument
from rag.config import parse_config


def _scanned_pdf_dir(tmp_path):
    """「掃描檔」替身:有頁面結構但文字層是空的。"""
    pdfs = tmp_path / "scanned"
    pdfs.mkdir()
    (pdfs / "scan.pdf").write_bytes(minimal_two_page_pdf("", ""))
    return pdfs


def _config(input_dir, **parsing_params):
    return parse_config(
        make_config(
            ingestion={
                "import": {
                    "method": "local_file",
                    "params": {"input_dir": str(input_dir), "extensions": [".pdf"]},
                },
                "parsing": {"method": "pdf", "params": parsing_params},
            }
        )
    )


def test_text_layer_pdf_extracted(pdf_dir):
    """有文字層的 PDF:行為與原 PyPDFToDocument 一致。"""
    pipelines = build_pipelines(_config(pdf_dir))
    result = pipelines.run_ingestion()
    assert result["writer"]["documents_written"] > 0
    assert result["empty_sources"] == []
    docs = pipelines.store.filter_documents()
    assert {d.meta["page"] for d in docs} <= {1, 2}


def test_scanned_pdf_reported_as_empty_source(tmp_path, caplog):
    """掃描檔(無文字層):檔案不靜默消失,警告與 empty_sources 都要出現。"""
    pipelines = build_pipelines(_config(_scanned_pdf_dir(tmp_path)))
    with caplog.at_level(logging.WARNING):
        result = pipelines.run_ingestion()
    assert result["empty_sources"] == ["scan.pdf"]
    assert result.get("writer", {}).get("documents_written", 0) == 0
    joined = " ".join(record.message for record in caplog.records)
    assert "沒有文字層" in joined  # 警告要說明原因並指路 custom converter
    assert "沒有產出任何切片" in joined


def test_unreadable_pdf_skipped_with_warning(tmp_path, caplog):
    pdfs = tmp_path / "bad"
    pdfs.mkdir()
    (pdfs / "broken.pdf").write_bytes(b"not a pdf at all")
    pipelines = build_pipelines(_config(pdfs))
    with caplog.at_level(logging.WARNING):
        result = pipelines.run_ingestion()
    assert result["empty_sources"] == ["broken.pdf"]


def test_unknown_parsing_param_rejected(pdf_dir):
    """pdf 方法已無參數;打錯欄位(如已移除的 ocr)要在建構期報錯。"""
    from rag.errors import ConfigError

    try:
        build_pipelines(_config(pdf_dir, ocr="auto"))
    except ConfigError as exc:
        assert "ocr" in str(exc)
    else:
        raise AssertionError("未知的 parsing 參數應報錯")


def test_component_direct_bytestream_meta_flow(pdf_dir):
    """ByteStream 路徑(auto 分流)的 meta 合併:doc_id 要跟著進 Document。"""
    from haystack.dataclasses import ByteStream

    data = (pdf_dir / "manual.pdf").read_bytes()
    stream = ByteStream(data=data, meta={"doc_id": "manual.pdf"})
    out = PdfToDocument().run(sources=[stream])
    assert len(out["documents"]) == 1
    doc = out["documents"][0]
    assert doc.meta["doc_id"] == "manual.pdf"
    assert "\f" in doc.content  # 頁界保留給下游 splitter
