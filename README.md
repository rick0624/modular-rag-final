# modular-rag-final

模組化 RAG(Retrieval-Augmented Generation,檢索增強生成)框架。

- RAG 的流程:先從知識庫**檢索**相關內容,再把內容連同問題交給 LLM **生成**回答。
- 本專案的核心是**十個模組**,每個模組有多種可換的方法。
  換方法只要改 YAML 設定檔的一行,不用改程式。
  另有三個選填模組(見下方模組表的說明)。
- 底層引擎是 [Haystack 2.x](https://haystack.deepset.ai/):
  元件執行、檢索器、生成器等成熟實作都交給它,
  本專案只維護一層薄薄的「設定檔 → pipeline」轉譯與檢查邏輯。
- 完全離線也能跑:內建 mock embedding 與 mock LLM,不需金鑰、不需網路。

```
Ingestion:  Import → Parsing → Chunking → Embedding → Indexing        (建索引)
Inference:  查詢 → Query Transformation → 檢索 → 重排 → 融合 → 生成    (回答問題)
Evaluation: 測試集逐題查詢 → hit rate / MRR                            (評估品質)
```

## Quick Start

```bash
pip install -r requirements.txt
python scripts/run_demo.py
```

執行後會看到:自動建立範例語料 → 建索引 → 查詢 → 印出檢索結果、
送給 LLM 的 prompt、回答,最後是評估分數(hit_rate / mrr)。全程離線。

跑測試(也全部離線):

```bash
python -m pytest
```

## 十個模組

每個模組(在設定檔中叫「槽位」)負責流程中的一件事。
`custom` 是共通選項:掛上自己寫的元件(見[新增自訂方法](#新增自訂方法))。

**Ingestion(建索引)**

| 模組 | 做什麼 | 可用方法 |
|---|---|---|
| 1 Import | 找出要匯入的文件 | `local_file` / `custom` |
| 2 Parsing | 把文件轉成純文字 | `auto` / `plain_text` / `pdf` / `clean` / `custom` |
| 3 Chunking | 把長文切成小段(切片) | `fixed_size` / `structure_based` / `page_based` / `no_chunking` / `custom` |
| 4 Embedding | 把切片轉成向量 | `mock` / `sentence_transformers` / `api_embedding` |
| 5 Indexing | 把切片與向量存進索引 | `in_memory` / `elasticsearch` |

**Inference(回答問題)**

| 模組 | 做什麼 | 可用方法 |
|---|---|---|
| 6 Query Transformation | 改寫查詢讓檢索更準 | `normalize` / `passthrough` / `glossary` / `jargon_mapping` / `llm_rewrite` / `llm_decompose` / `llm_multi_hyde` / `preqrag` / `custom` |
| 7 Retrieval | 從索引找出相關切片 | `bm25` / `embedding` / `hybrid` / `custom` |
| 8 Reranking | 把檢索結果重新排序 | `none` / `similarity` / `api_rerank` / `insertrank` / `custom` |
| 9 Generation | 用 LLM 生成回答 | `mock` / `openai` / `gateway_openai_compatible` / `custom` |
| 10 Evaluation | 算檢索品質指標 | `basic_retrieval_metrics` |

**選填模組**(設定檔省略 = 不做):

| 模組 | 做什麼 | 定位 |
|---|---|---|
| fusion | 多個子查詢的結果融合;也能按文件/頁聚合 | 多子查詢機制的內建融合步驟(查詢被拆解時必經) |
| routing | 查詢分類(結果附在輸出上,不影響檢索) | 為整合 Online 系統而做 |
| formatter | 把最終結果組成對外格式 | 為整合 Online 系統而做 |

routing 與 formatter 是為了讓 Online 系統直接取用結果而加的支線;
未來可以評估是否整併進十個核心模組(見文末[貢獻方向](#貢獻方向))。

每個方法的參數與預設值,見 [docs/methods.md](docs/methods.md)。

## 專案結構

```
configs/
  default.yaml              預設設定檔,也是「方法型錄」:所有方法與參數都展示在裡面
  custom_demo.yaml          custom 機制示範(inference 端)
  custom_ingestion_demo.yaml custom 機制示範(ingestion 端)
  online_full_demo.yaml     Online 系統測試用:必要配置已設立完成,填金鑰即可跑
rag/                        框架本體
  builder.py                核心:把設定檔轉成 Haystack pipeline
  methods_ingestion.py      ingestion 端方法型錄(方法名 → 元件)
  methods_inference.py      inference 端方法型錄(方法名 → 元件)
  config.py                 設定檔載入、驗證、${ENV_VAR} 展開
  slots.py                  方法型錄的基礎類別(SlotFactory、參數驗證)
  compatibility.py          建構期的方法組合相容性檢查
  custom.py                 custom module 的載入與契約驗證
  evaluation.py             評估(hit rate / MRR)
  kb_meta.py                ingestion 指紋與增量 ingest 的紀錄
  trace.py                  逐步紀錄的整理與排版
  logging_config.py         log 檔與警告總結
  errors.py                 錯誤型別(繁中錯誤訊息)
  text.py                   小工具(從 LLM 回覆抽 JSON)
  components/               自製的 Haystack 元件
    ingestion_steps.py      ingestion 流程的固定步驟(列檔、蓋章、增量過濾…)
    multi_query.py          多子查詢的檢索調度
    fusion.py               子查詢結果融合
    query_transforms.py     查詢改寫類元件(normalize / LLM 改寫 / 拆解…)
    llm_rerankers.py        InsertRank LLM 重排
    api_clients.py          通用 HTTP embedding / rerank 客戶端
    gateway_generator.py    Online 系統閘道 LLM 客戶端 + mock LLM
    mock_embedders.py       離線用的假 embedding
    pdf.py                  PDF 文字抽取(pypdf)
    side_branches.py        routing 與 formatter 元件
custom_modules/             自訂元件的範例骨架(接 Online 系統時複製來改)
scripts/
  run_demo.py               主要執行入口:建索引 → 查詢 → 評估
  experiment.py             管線組合實驗(批次比較不同方法組合,見 docs/experiments.md)
  validate.py               跑全部 1250 題 QA dataset 的完整驗證(自訂 evaluation)
  sample_data.py            demo 用的範例語料
tests/                      測試(全部離線,不碰網路)
docs/
  methods.md                所有方法與參數的完整型錄
  interfaces.md             custom 元件的輸入輸出契約
  operations.md             進階操作手冊(本 README 沒展開的細節都在這)
  experiments.md            管線組合實驗指南(experiment.py 的用法與注意事項)
requirements.txt            基本依賴(離線可跑)
requirements-online.txt     Online 系統整合依賴(Elasticsearch + sentence-transformers)
.env.example                金鑰範本(複製成 .env 填入)
```

## 環境與安裝

需要 Python 3.10+。依賴分兩份:

```bash
pip install -r requirements.txt            # 基本:離線可跑,開發與測試夠用
pip install -r requirements-online.txt     # 接 Online 環境再裝:ES + 本地模型
```

請在 repo 根目錄執行。`requirements.txt` 內含 `-e .`,會把 `rag` 套件
本身也裝進環境——自己的腳本或 notebook 才能 `import rag`。

也可以用套件形式安裝,效果相同:
`pip install -e ".[dev]"` 或 `pip install -e ".[dev,online]"`。

## 執行、測試與實驗

```bash
python scripts/run_demo.py                              # 預設設定檔,全流程
python scripts/run_demo.py --query "你的問題"            # 指定問題
python scripts/run_demo.py --config configs/custom_demo.yaml   # 指定設定檔
python scripts/run_demo.py --trace                      # 印出中間每一步
python scripts/run_demo.py --stage ingestion            # 只建索引
python scripts/run_demo.py --stage inference            # 只查詢(索引沿用)
```

- `--trace` 用來除錯:看改寫後的查詢、每路檢索與重排的結果。
- `--stage` 用來分工:索引建一次,之後調 prompt / 重排時不必重建。
- 每次執行都會自動寫完整 log 到 `logs/`。

```bash
python -m pytest                                        # 全部測試(離線)
ES_URL=http://<你的 ES>:9200 python -m pytest -m es      # ES 整合測試(選配)
python scripts/experiment.py                            # 批次比較方法組合(詳見 docs/experiments.md)
```

trace / log / 分階段的完整說明,見 [docs/operations.md](docs/operations.md)。

## 設定檔怎麼用

一個設定檔描述一整條 pipeline。每個模組固定這個形狀:

```yaml
  embedding:
    method: sentence_transformers      # 用哪個方法:改這一行就換方法
    method_params:                     # 各方法的參數,分區並存
      sentence_transformers:
        model_name: sentence-transformers/all-MiniLM-L6-v2
      api_embedding:                   # 沒被選中的區塊放著不影響
        endpoint: https://api.example.com/v1/embeddings
```

只有一個方法時也可以寫扁平的 `params:`。要點:

- **方法鏈**:parsing、query_transformation、reranking 可以把 `method`
  寫成清單依序執行,例如 `method: [normalize, llm_decompose]`。
- **金鑰注入**:設定值可寫 `${ENV_VAR}`,載入時從環境變數(或 `.env`)展開。
  金鑰因此不會進版控。
- **錯誤提早報**:方法名打錯、參數打錯、組合不相容,都在建 pipeline 時
  就報錯,錯誤訊息會指出位置與可用的選項。

完整的方法與參數示範都在 [configs/default.yaml](configs/default.yaml),
建議直接打開看,每個參數都有註解。

## Online 系統套用此框架之測試方式

1. 設定檔選用 `configs/online_full_demo.yaml`:
   Online 環境的必要配置(embedding API、ES 索引、LLM 閘道…)已設立完成
2. 裝依賴套件:`pip install -r requirements-online.txt`
3. 填金鑰:`cp .env.example .env`,填入 API 金鑰與 ES 連線資訊
4. 建索引:`python scripts/run_demo.py --config configs/online_full_demo.yaml --stage ingestion`
5. 查詢:`python scripts/run_demo.py --config configs/online_full_demo.yaml --stage inference --query "測試問題"`

要調整組合(換方法、改參數)時,直接改 `online_full_demo.yaml` 對應模組
的 `method`;所有可用方法與參數示範見 `configs/default.yaml` 型錄。
ES 認證排錯、API 回應欄位對不上的對映設定,
見 [docs/operations.md](docs/operations.md) 第 4–6 節。

### 測試用的兩支腳本

配置跑通之後,用這兩支腳本做完整測試:

- `scripts/validate.py`:跑**全部 1250 題的 QA dataset** 做完整驗證,
  以自訂的 evaluation 方法計分,用來確認 Online 配置的整體品質。
- `scripts/experiment.py`:**測試各種不同方法與參數的組合**,
  找出效果最好的配置;用法詳見 [docs/experiments.md](docs/experiments.md)。

## 新增自訂方法

Online 系統特有的邏輯(自家的檢索 API、切塊規則…)不用改框架,
寫一個元件掛上去就好:

**1. 寫一個 Haystack 元件**(一個 `.py` 檔,放哪都行):

```python
from haystack import component

@component
class BySentenceSplitter:
    """把每條查詢依句號拆成多條。"""

    @component.output_types(queries=list[str])
    def run(self, queries: list[str]):
        out = [s.strip() for q in queries for s in q.split("。") if s.strip()]
        return {"queries": out}
```

**2. 在設定檔掛進模組**:

```yaml
  query_transformation:
    method: custom
    params:
      file: ./my_transform.py     # 路徑相對「執行目錄」
      class: BySentenceSplitter
```

**3. 跑起來驗證**:`python scripts/run_demo.py --config configs/my.yaml --trace`

每個模組的元件要吃什麼輸入、吐什麼輸出(契約),
見 [docs/interfaces.md](docs/interfaces.md);寫錯的話建 pipeline 時會報錯並指明修法。

**現成的範例骨架**在 [custom_modules/](custom_modules/):
十種模組各一個,`TODO(替換點)` 標明要換入真實邏輯的位置。
兩份示範設定檔可以直接跑:

```bash
python scripts/run_demo.py --config configs/custom_demo.yaml --trace
python scripts/run_demo.py --config configs/custom_ingestion_demo.yaml --trace
```

完整規則(方法鏈限制、log 慣例、指紋影響…)與「把方法加進框架型錄」
的作法,見 [docs/operations.md](docs/operations.md) 第 10–11 節;
在自己的程式裡呼叫框架(Python API)見第 9 節。

## 貢獻方向

想參與開發的話,目前有四個明確的方向:

1. **UI 層**:研究
   [haystack-rag-app](https://github.com/deepset-ai/haystack-rag-app)
   (deepset 官方的 Haystack RAG 前後端範例專案),
   評估作為本框架 UI 層的可行性。
2. **模組架構優化**:選填模組的整併與 pipeline 彈性化 ——
   例如把 formatter 整併進 generation 模組、
   讓 fusion 的擺放位置可以自由決定(更彈性地制定 pipeline)。
3. **進階 RAG 架構整合**:Knowledge Graph(知識圖譜)、
   其他 advanced RAG techniques 的引入。
   通用的方法走「進框架型錄」路線,見上方[新增自訂方法](#新增自訂方法)。
4. **實驗搜索方式優化**:配置組合實驗目前只有
   one_at_a_time 與 product 全掃兩種模式(見
   [docs/experiments.md](docs/experiments.md)),
   可以引入更聰明的搜索策略(例如逐步收斂、早停)。
