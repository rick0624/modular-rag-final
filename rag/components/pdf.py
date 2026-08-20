"""PDF converter:pypdf 文字層抽取。

已知限制(pypdf 先天):

1. **掃描檔(圖片型 PDF)**:文字層是空的,什麼都抽不到 —— 該頁會是
   空白,並記警告(至少不靜默消失)。
2. **多欄 / 表格版面**:pypdf 按 PDF 內部串流順序抽字,視覺上相鄰的
   內容在抽出的文字流中可能相隔數百字元。

這類語料需要 OCR(按視覺位置輸出文字)才能正確處理;本框架不內建,
有需求時以 ``parsing: custom`` 掛自訂 converter 接入。

輸出與 PyPDFToDocument 相容:每檔一個 Document、頁與頁之間以 ``\\f``
分隔(下游 splitter 據此標頁碼)、meta 沿用 ByteStream / meta 清單。
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

from haystack import Document, component
from haystack.components.converters.utils import (
    get_bytestream_from_source,
    normalize_metadata,
)
from haystack.dataclasses import ByteStream

logger = logging.getLogger(__name__)


@component
class PdfToDocument:
    """PDF → Document(pypdf 文字層)。"""

    def _convert(self, bytestream: ByteStream, label: str) -> str | None:
        """單一 PDF → 全文(頁以 \\f 分隔);完全讀不到時回 None。"""
        from pypdf import PdfReader

        data = bytestream.data
        try:
            reader = PdfReader(io.BytesIO(data))
            page_texts = [
                (page.extract_text() or "").strip() for page in reader.pages
            ]
        except Exception as exc:
            logger.warning("無法讀取 PDF %s(%s: %s),跳過", label, type(exc).__name__, exc)
            return None

        empty = [index for index, text in enumerate(page_texts) if not text]
        if empty:
            logger.warning(
                "PDF %s 有 %d 頁沒有文字層(掃描頁或圖片頁),這些頁面將是空的;"
                "需要 OCR 時請以 parsing: custom 掛自訂 converter。",
                label, len(empty),
            )
        return "\f".join(page_texts)

    @component.output_types(documents=list[Document])
    def run(
        self,
        sources: list[str | Path | ByteStream],
        meta: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        meta_list = normalize_metadata(meta, sources_count=len(sources))
        documents: list[Document] = []
        for source, metadata in zip(sources, meta_list):
            try:
                bytestream = get_bytestream_from_source(source)
            except Exception as exc:
                logger.warning(
                    "無法讀取來源 %s(%s: %s),跳過", source, type(exc).__name__, exc
                )
                continue
            merged_meta = {**bytestream.meta, **metadata}
            label = str(merged_meta.get("doc_id") or source)
            content = self._convert(bytestream, label)
            if content is None:
                continue
            documents.append(Document(content=content, meta=merged_meta))
        return {"documents": documents}
