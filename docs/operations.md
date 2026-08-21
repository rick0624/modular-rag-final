# 進階操作手冊

這份文件收錄 README 沒有展開的進階操作與細節。
建議先讀完 [README](../README.md) 再來查這裡。

目錄:

1. [分階段執行與 ingestion 指紋](#1-分階段執行與-ingestion-指紋)
2. [逐步紀錄(trace)與 log 檔](#2-逐步紀錄trace與-log-檔)
3. [用自己的文件建索引](#3-用自己的文件建索引)
4. [連到有認證的 Elasticsearch](#4-連到有認證的-elasticsearch)
5. [api_embedding 回應形狀對映表](#5-api_embedding-回應形狀對映表)
6. [api_rerank 請求與回應形狀對映表](#6-api_rerank-請求與回應形狀對映表)
7. [接入實際 LLM](#7-接入實際-llm)
8. [檢索-only 模式](#8-檢索-only-模式)
9. [程式接入(Python API)](#9-程式接入python-api)
10. [custom module 的完整規則](#10-custom-module-的完整規則)
11. [路 B:把方法加進框架型錄](#11-路-b把方法加進框架型錄)
12. [設計要點](#12-設計要點)

---

## 1. 分階段執行與 ingestion 指紋

`--stage` 決定這次執行要做哪一段:

| `--stage` | 做什麼 |
|---|---|
| `all`(預設) | 建索引 → 查詢 → 評估,一次做完 |
| `ingestion` | 只建索引,建完就結束 |
| `inference` | 跳過建索引,直接查詢 + 評估 |

為什麼要分階段?建索引很花時間(要切塊、算 embedding)。
如果你只是在調 prompt 或改重排方法,用 `--stage inference` 就不必每次重建索引。

```bash
python scripts/run_demo.py --config my.yaml --stage ingestion    # 先建索引
python scripts/run_demo.py --config my.yaml --stage inference --query "你的問題"
```

**ingestion 指紋**是這個機制的安全鎖。原理:

- 建索引時,框架把 config 中 ingestion 區塊的雜湊值(sha256)寫在索引旁邊。
- `--stage inference` 啟動時,重新計算雜湊並比對。
- 對不上就報錯。意思是:「設定改了,但索引還是舊的,查詢結果會不準」。

補充細節:

- 雜湊用的是**展開前**的原始 config。`${ENV_VAR}` 佔位符不會展開,
  所以金鑰不會進雜湊。註解、排版、鍵順序也不影響指紋。
- 指紋存放位置:ES 存在索引 mapping 的 `_meta`;in_memory 存在
  process 內(重啟就消失)。

`--stage inference` 的前提是索引裡已經有內容:

| 情形 | 行為 |
|---|---|
| `indexing: elasticsearch`(索引先前建好) | 比對指紋,不符會報錯 |
| `retrieval: custom`(外部檢索,不用本地索引) | 直接跑 |
| `indexing: in_memory` | 索引是空的,查不到東西(會印警告) |

程式接入時對應 `build_pipelines(config, stage=...)`。
沒建的那條 pipeline 在回傳物件上是 `None`,誤呼叫會報錯並說明怎麼重建。

## 2. 逐步紀錄(trace)與 log 檔

### trace:看每一步做了什麼

終端機預設只印重點。加 `--trace` 可以看到中間每一步:

```bash
python scripts/run_demo.py --trace
python scripts/run_demo.py --trace --trace-docs 0   # 每步印出全部切片(不截斷)
```

會列出:ingestion 每步的產出筆數、查詢改寫前後的文字、
每條子查詢在各路檢索與每段重排後的結果(含分數與被移除的切片)、
fusion 的最終結果。

寫程式時可以直接拿 trace 資料,不必解析終端機輸出:

```python
result = pipelines.query("...")
for step in result["trace"]["subqueries"][0]["steps"]:
    print(step["component"], step["type"], len(step["documents"]))
```

### log 檔:每次執行的完整紀錄

每次執行都會自動寫一份 log 到 `logs/run-<時間戳>.log`,路徑印在執行結束時。
log 檔的內容比終端機完整:

| | 終端機 | log 檔 |
|---|---|---|
| 層級 | `--log-level`(預設 WARNING) | 一律 DEBUG |
| 逐步紀錄 | 只在 `--trace` 時 | 一律完整 |
| 每步切片 | 依 `--trace-docs` 截斷(預設 5) | 全印 |
| LLM 的 prompt 與回覆 | 需 `--log-level DEBUG` | 一律記錄 |
| HTTP 請求細節 | 不印 | 記錄 |

`--log-file` 指定路徑,`--no-log-file` 關閉。

注意:log 檔是 UTF-8。Windows PowerShell 5.1 讀檔要加編碼旗標,
否則中文會變亂碼:`Get-Content logs\run-xxx.log -Encoding UTF8`。

### fail-soft:降級不中斷

外部服務掛掉時(API 逾時、LLM 回覆解析不了),框架不會讓整次查詢失敗,
而是**保留原本的結果繼續走**,同時記一筆 WARNING,訊息帶 `fail-soft:` 前綴。

執行結束時終端機會總結本次所有警告。**沒有這段總結 = 全程沒有任何降級**。
要找歷史紀錄:`grep fail-soft logs/run-*.log`。

程式接入:`rag.logging_config.setup_logging()` 設定 log、
`rag.logging_config.warning_tally()` 取得本次全部警告。

## 3. 用自己的文件建索引

把文件放進一個資料夾(txt / md / pdf 可以混放,子資料夾也會掃到),
把 config 的 `import.params.input_dir` 指過去即可。

運作方式:

- `local_file` 是萬用 importer,預設收 `.txt` / `.md` / `.pdf`。
- `parsing: auto` 會依檔案類型自動分流(txt/md 走文字解析、pdf 走 pypdf)。
- 一個 config = 一個知識庫(KB),全部文件進同一個索引。

**extensions 與 parser 的搭配規則**:

- `extensions` 收窄成同一類型(全文字或全 PDF)→ 可以用單類型 parser
  (`plain_text` 或 `pdf`)。
- 混合類型 → 只有 `auto` 能接。
- 搭錯會在建 pipeline 時報錯,錯誤訊息會提示改用 `auto`。

常見調整:

- **掃描 PDF**:pypdf 只能抽文字層。掃描檔(整頁是圖片)抽不出字,
  該頁會是空的,並印警告(不會靜默消失)。需要 OCR 時,
  用 `parsing: custom` 掛自己的 converter(契約見 [interfaces.md](interfaces.md))。
- **換切法**:`chunking.method` 可改 `page_based`(按頁切)或
  `structure_based`(按段落結構切)。版面雜訊多時,parsing 改成鏈
  `[auto, clean]` 先清理。
- **換 embedding 模型後必須重建索引**:換索引名,或先刪舊索引。
  ES 的向量欄位維度(dims)建立後不能改。

**增量 ingest**(`indexing.params.incremental: true`),重跑時跳過沒變的部分:

- **檔案層**:內容沒變的檔案,連解析都跳過
  (依檔案 bytes 雜湊判斷;parsing / chunking 設定變了會全部重解析)。
- **切片層**:內容沒變的切片,跳過 embedding 與寫入。
- 執行結果的 `skipped_files` / `skipped_unchanged` 顯示兩層各跳過多少。

**upsert 語意**:重複 ingest 是「更新或新增」,**不會刪除**已移除檔案的舊切片。
來源檔案刪減後想要乾淨的索引:換索引名,或先刪索引再重建。

**評估集**:自備 JSONL 時,每行格式是
`{"query": "...", "relevant_doc_ids": ["..."]}`,
`doc_id` 就是檔案相對 `input_dir` 的路徑(例如 `manual.pdf`)。

## 4. 連到有認證的 Elasticsearch

本地開發、沒開 security 的 ES 不用帶憑證。
公司或雲端叢集預設開著 security,沒帶憑證時第一個請求就會失敗:

```
AuthenticationException(401, 'security_exception',
  'missing authentication credentials for REST request [/]')
```

這不是設定錯誤,是**還沒設定認證**。在 `indexing` 的參數補上一組(兩者擇一):

```yaml
indexing:
  method: elasticsearch
  method_params:
    elasticsearch:
      hosts: ${ES_URL}
      index: my-index
      username: ${ES_USERNAME}     # basic auth,需與 password 成對
      password: ${ES_PASSWORD}
      # api_key: ${ES_API_KEY}     # 或改用 API key(base64 的 "id:api_key")
      # ca_certs: ${ES_CA_CERTS}   # https 且憑證由私有 CA 簽發時
```

金鑰用 `${ENV_VAR}` 寫法,實際值放 `.env`(不進版控)。

排錯提示:

- `username` / `password` 必須成對,且不能與 `api_key` 同時設。
  設錯會在建 pipeline 時就報錯,不會拖到送請求才失敗。
- 錯誤變成 `403` = 認證通了,但帳號權限不足
  (需要目標索引的 `create_index` / `read` / `write` 權限)。
- 連線階段的 TLS 錯誤 = 用 `ca_certs` 指到公司的 CA 憑證。
- 憑證也可以寫在 URL 裡(`https://user:pass@host:9200`),
  但 URL 常被記進 log,建議還是用上面的欄位。

## 5. api_embedding 回應形狀對映表

`api_embedding` 是通用的 HTTP embedding 客戶端。
不同家 API 的回應結構不同,用參數對映,不用改程式:

| API 回應結構 | 設定 |
|---|---|
| `{"embeddings": [[...], ...]}` | 預設值即可 |
| `{"result": {"embeddings": [[...], ...]}}` | `embeddings_field: result.embeddings` |
| `{"data": [{"embedding": [...]}, ...]}`(OpenAI 式) | `embeddings_field: data` + `item_field: embedding` |
| `[[...], ...]`(回應本身就是清單) | `embeddings_field: null` |

欄位對不上時,錯誤訊息會列出回應中實際存在的欄位,照著改就好。

## 6. api_rerank 請求與回應形狀對映表

`api_rerank` 同理。預設對應的形狀:請求 `{"question", "documents", "model"}`、
回應 `{"returnData": [{"index", "score"}]}`。

| API 形狀 | 設定 |
|---|---|
| 請求 `{"query", "documents"}` | `query_field: query` |
| 回應 `{"results": [{"index", "relevance_score"}]}`(Cohere 式) | `results_field: results` + `score_field: relevance_score` |
| 回應 `[{"index", "score"}]`(回應本身就是清單) | `results_field: null` |
| 回應的 `index` 從 1 起算 | `index_base: 1` |
| 分數是「距離」(越小越相關) | `higher_is_better: false` |

行為上要知道的幾件事:

- **`index` 是候選在送出清單中的位置**,不是文件 id。
  `index_base` 設錯會讓結果整體位移一格。全部越界時會報錯並提示;
  只差一格而沒越界時偵測不到,接線前請先確認 API 文件。
- **回應沒列出的候選視同淘汰**。
- **不自動分批**:rerank 分數只在同一次呼叫內可以比較,分批會讓排序失真。
  候選數量由 `retrieval` 的 `top_k × boost_k_factor` 決定,
  API 有長度上限時從那裡調小。
- **fail-soft**:API 掛掉時保留原本的檢索順序(前 `top_k` 筆),查詢不中斷。
  初次接線建議先設 `raise_on_failure: true`,把欄位對映確認好再關掉。
- **多子查詢會多次呼叫**:查詢被拆成 N 個子查詢時,重排會呼叫 N 次 API。

## 7. 接入實際 LLM

generation 槽位的三個真實選項:

- **`openai`**:官方 OpenAI,或任何相容服務(vLLM、Ollama、Groq…,
  用 `api_base_url` 指定)。金鑰預設讀環境變數 `OPENAI_API_KEY`。
- **`gateway_openai_compatible`**:為公司內部閘道設計,有兩個特別行為:
  - `model` 不設定時,請求**完全不帶**這個欄位(官方 SDK 做不到,
    有些閘道不接受 model 欄位)。
  - 遇到 OpenAI 推理模型(gpt-5 / o 系列)自動忽略 `temperature`、
    改送 `max_completion_tokens`,YAML 不用改。
- **`custom`**:非 OpenAI 相容的內部服務,自己寫元件(見 README「新增自訂方法」)。

**generator 沿用規則**:`llm_rewrite`、`llm_decompose`、`llm_multi_hyde`、
`preqrag`、`insertrank` 這些會呼叫 LLM 的方法,都有 `params.generator` 參數:

- 不設定 → 沿用 generation 槽位的 LLM 設定(各自建新實例)。
  整條 pipeline 只需要接一個 LLM 來源。
- 有設定 → 用自己指定的(格式 `{method, params}`,吃 generation 的任一方法,
  包含 mock 腳本,測試時很好用)。

## 8. 檢索-only 模式

只需要檢索結果、不需要 LLM 生成答案時,在 `inference` 設
`generate_answer: false`:

- pipeline 止於 fusion(去重、排序、取 top_k),不會呼叫 LLM。
- `query()` 回傳的欄位不變,但 `answer` / `prompt` / `reply_meta` 是 `None`,
  檢索結果照常在 `documents`。
- `generation` 區塊此時可以省略。保留的話,只作為上面那些 LLM 方法的
  沿用來源。兩者都沒有時,LLM 方法必須各自指定 `params.generator`。

典型組合:術語替換(`jargon_mapping`)→ LLM 改寫(`llm_rewrite`)→
hybrid 檢索放大候選(`boost_k_factor`)→ cross-encoder 收斂(`similarity`)
→ fusion 回傳 top k。

## 9. 程式接入(Python API)

不透過 CLI、直接在自己的程式裡使用框架。前提:`rag` 套件已裝進環境
(`pip install -r requirements.txt` 已包含,或單獨 `pip install -e .`;
沒裝會遇到 `No module named 'rag'`):

```python
from rag import build_pipelines, load_config

config = load_config("configs/default.yaml")
pipelines = build_pipelines(config)          # 可加 stage="ingestion" / "inference"
pipelines.run_ingestion()                    # 建索引
result = pipelines.query("FAISS 支援哪些索引結構?")

result["answer"]      # LLM 的回答(檢索-only 模式時為 None)
result["documents"]   # 融合後的切片(meta 含 doc_id / page / group_key / sources)
result["prompt"]      # 實際送出的 prompt(可稽核)
result["routing"]     # 查詢分類結果(未設 routing 模組時為 None)
result["trace"]       # 逐步紀錄(見第 2 節)
```

評估:`from rag.evaluation import run_evaluation`,
傳入 pipelines 與 config 即可拿到 hit_rate / MRR。

## 10. custom module 的完整規則

README 的「新增自訂方法」講了最短路徑。這裡是完整規則,
寫自己的元件前建議掃一遍:

- **額外的輸出 socket 允許**(會自動收進 trace);
  **額外的必填輸入不允許**(執行時沒有上游會餵它)。
  需要設定值就給預設值,或用 `init_params` 傳進去。
- **外部欄位轉成 Document 是元件自己的責任**:外部系統的回應在
  custom retrieval 裡轉成 Haystack `Document`
  (內文 → `content`、分數 → `score`、其餘 → `meta`)。
  建議一併補 `meta["doc_id"]` 與 `meta["chunk_id"]`,
  這樣 trace、fusion 的按文件聚合與 evaluation 才能直接運作。
- custom 可以放在方法鏈中(`method: [normalize, custom]`),
  但同一條鏈只能有一個 custom。需要兩個時,把邏輯合併成一個元件,
  或走路 B。
- **log 要看得到**:把 logger 命名在 `rag.*` 底下,例如
  `logging.getLogger("rag.custom.my_transform")`(範例骨架都是這樣寫)。
  這樣終端機只印 WARNING 以上,細節照樣進 log 檔。
  用 `logging.getLogger(__name__)` 在 `file:` 載入時也可以,
  但 `class_path:` 載入時 INFO / DEBUG 會被丟掉。
- **generation 的 custom 是「換掉 LLM 客戶端」,不是換掉 prompt 組裝**:
  prompt 照常寫在 YAML,元件收到的是框架組好的 messages。
  OpenAI 相容的閘道不需要寫 custom,直接用 `gateway_openai_compatible`。
- **fusion 掛了 custom 就一律執行**:單一查詢也會進元件,
  要不要原樣通過由元件自己決定。建議額外輸出 `applied: bool` 供 trace 區分。
  跨子查詢的原始分數不能直接比較,安全預設是名次法(RRF)。
  與內建參數(group_by / strategy / top_k)互斥,混用會在載入時報錯。
- **formatter 的信封固定、內容自由**:socket 名稱(`payload`)與
  `query()` 的鍵(`output`)固定,payload 的型別由元件自己決定。
  這是終端槽位的特權(沒有下游接它),中間槽位不可模仿。
- **ingestion 端的相容性宣告寫在 config 參數裡**:import 的 `content_type`、
  parsing 的 `kind` / `produces_pages` / `input_content_types`、
  chunking 的 `requires_pages`。省略就跳過檢查或用預設。
- **`file:` 的檔案內容會進 ingestion 指紋**:改了解析或切塊邏輯 =
  索引內容過期,增量 ingest 的檔案層紀錄也會作廢(全部重解析)。
  `class_path:` 只有路徑字串進指紋,偵測不到內容變更 ——
  要指紋保護就用 `file:`。另外 `--stage inference` 的查詢端主機
  也要有同一份 `.py`,否則指紋對不上。
- **custom import 回傳非本地路徑時**(ByteStream / API 參照),
  檔案層增量無法比對雜湊,會退化為每次全部重解析(有警告;
  切片層增量仍會跳過沒變的 embedding)。
- embedding / indexing 槽位**不支援 custom**
  (它們的產出不是單一元件),有需求走路 B。
- 安全提醒:custom module 就是執行任意 Python 程式碼,
  與 config 檔同一信任層級,只載入你信任的來源。

## 11. 路 B:把方法加進框架型錄

custom module(路 A)適合公司特定的邏輯。
如果一個方法**夠通用、想讓所有人在 YAML 直接選用**,就走路 B:

1. 寫元件(同路 A)。
2. 在方法型錄檔加一組 factory:inference 端改 `rag/methods_inference.py`,
   ingestion 端改 `rag/methods_ingestion.py`:

```python
class _BySentenceParams(BaseParams):   # extra="forbid":打錯參數直接報錯
    pass

def _build_by_sentence(raw, ctx):
    validate_params("query_transformation", "by_sentence", _BySentenceParams, raw)
    return BySentenceSplitter()

TRANSFORM_FACTORIES["by_sentence"] = SlotFactory(build=_build_by_sentence)
```

(`BaseParams` / `validate_params` / `SlotFactory` 都在 `rag/slots.py`。)

3. 在 YAML 改 `method: by_sentence`,完成。

有相容性需求時,在 `SlotFactory` 上宣告(`requires_pages`、
`required_capabilities` 等),builder 會自動檢查。

## 12. 設計要點

- **分工**:Haystack 負責元件執行、socket 型別驗證與成熟實作
  (converter / splitter / retriever / ranker / generator…);
  本框架的薄 builder 負責「YAML → pipeline」的翻譯、語意相容性檢查、
  繁中錯誤訊息。
- **同向量空間紀律**:查詢端的 embedder 一律由 `ingestion.embedding`
  派生,保證查詢與文件用同一個模型、同一個向量空間。
- **`Document.id = chunk_id`**(格式 `"{doc_id}::chunk_{seq}"`):
  相同輸入必產生相同 id,重複 ingest 就是 upsert,ES 的 `_id` 穩定。
- **離線優先**:mock embedding / mock LLM 是一級公民。
  所有測試不碰網路,LLM 行為用腳本化的 mock 驗證。
- **相依版本**:`haystack-ai>=2.31,<3`;sentence-transformers 元件從
  整合套件 import(2.32 起移出 core);`elasticsearch-haystack>=6.3`(ES 8.x)。
