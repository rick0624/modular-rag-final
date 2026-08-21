# 管線組合實驗(experiment.py)

`scripts/experiment.py` 用來回答一個問題:**「哪一種方法組合的效果最好?」**

它會自動產生多個 config 組合、逐一跑查詢、收集結果。
你不用手動改 config 檔再一個一個跑。

定位:這支腳本只負責「跑出原始結果」。
要算分數(hit_rate / MRR)請接上評估,見[第 5 節](#5-接上評估指標)。

目錄:

1. [快速開始](#1-快速開始)
2. [兩種比較模式(MODE)](#2-兩種比較模式mode)
3. [SLOT_OPTIONS:設定要比較什麼](#3-slot_options設定要比較什麼)
4. [選項的四種寫法](#4-選項的四種寫法)
5. [接上評估指標](#5-接上評估指標)
6. [保存結果與重現組合](#6-保存結果與重現組合)
7. [注意事項](#7-注意事項)

---

## 1. 快速開始

實驗的設定都寫在 `scripts/experiment.py` 最上面的「實驗定義」區塊,
共四個變數:

| 變數 | 意思 |
|---|---|
| `BASE_CONFIG` | 基底設定檔(預設 `configs/default.yaml`);每個組合都從它出發修改 |
| `MODE` | 比較模式:`one_at_a_time` 或 `product`(見第 2 節) |
| `SLOT_OPTIONS` | 要比較的模組與選項(見第 3 節) |
| `QUERIES` | 每個組合都會問的測試問題 |

改好之後,在 repo 根目錄執行:

```bash
python scripts/experiment.py
```

執行後每個組合印一行,像這樣:

```
[OK]   baseline  各題檢回 [3, 3]
[OK]   retrieval=bm25  各題檢回 [3, 3]
[OK]   retrieval=embedding  各題檢回 [3, 2]
[FAIL] retrieval=hybrid: ConfigError: ...
```

- `[OK]` 後面是組合名稱(label)與每題檢索回來的切片數。
- `[FAIL]` 表示這個組合建不起來或跑失敗;**一個組合失敗不會中斷整批**,
  錯誤訊息記在該筆結果裡。

## 2. 兩種比較模式(MODE)

### `one_at_a_time`(預設):一次只動一個模組

先跑一次「什麼都不改」的基線(baseline),
然後每個選項各跑一次 —— 每次只改一個模組,其他維持基底設定。

適合:**想知道哪個模組對結果影響最大**。
組合數 = 1(基線)+ 所有選項的總數,不會爆炸。

### `product`:全交叉乘積

把 `SLOT_OPTIONS` 裡所有模組的選項互相搭配,每種搭配都跑。

適合:**懷疑兩三個模組之間有交互作用**
(例如「hybrid 檢索是不是要配 rerank 才有效?」)。

注意組合數是相乘的:3 個檢索方法 × 4 個重排方法 = 12 個組合。
用 `product` 前,先把 `SLOT_OPTIONS` 收窄到 2–3 個你關心的模組。

## 3. SLOT_OPTIONS:設定要比較什麼

`SLOT_OPTIONS` 是一個 dict:**key 是模組的位置,value 是要比較的選項清單**。

模組位置的寫法是「區塊.模組名」,例如:

```python
SLOT_OPTIONS = {
    "inference.retrieval": ["bm25", "embedding", "hybrid"],
    "inference.query_transformation": ["passthrough", "normalize"],
}
```

這個設定的意思:比較三種檢索方法、兩種查詢轉換方法。
`one_at_a_time` 模式下會跑 1 + 3 + 2 = 6 個組合。

一條規則:**同一個模組只能出現在一個 key 底下**。
兩個 key 都想改同一個模組時,腳本會直接報錯,
請把它們合併成一個 bundle(見下一節)。

## 4. 選項的四種寫法

選項清單裡的每個元素,可以是四種形式:

### 寫法一:字串 —— 只換方法名

```python
"inference.retrieval": ["bm25", "hybrid"]
```

只改 `method` 那一行。參數沿用 `BASE_CONFIG` 裡
`method_params` 型錄的設定(這就是型錄並存的好處)。

### 寫法二:list —— 方法鏈

```python
"inference.query_transformation": [
    "normalize",
    ["normalize", "llm_decompose"],   # 鏈:先正規化,再 LLM 拆解
]
```

### 寫法三:dict —— 整個模組配置直接替換

要**自訂參數**,或要動 **fusion 這類基底沒啟用的模組**時用:

```python
"inference.reranking": [
    "none",
    {"method": "insertrank", "params": {"top_k": 3}},
]
```

注意:dict 是「整個模組換掉」,基底的 `method_params` 型錄不會保留。

### 寫法四:bundle —— 多個模組綁在一起換

有些設定必須一起換才有意義
(例如換了 embedding 模型,ES 的 index 也得跟著換,見第 7 節)。
bundle 的寫法:**dict 的 key 是模組位置**(含「.」),
外層的 key 只是這個比較維度的名字(自己取):

```python
SLOT_OPTIONS = {
    "embedding_變體": [
        {
            "_label": "model-a",          # 這個選項的顯示名稱(選填)
            "ingestion.embedding": {
                "method": "api_embedding",
                "params": {"endpoint": "https://...", "model": "model-a"},
            },
            "ingestion.indexing": {
                "method": "elasticsearch",
                "params": {"hosts": "${ES_URL}", "index": "exp-model-a"},
            },
        },
        {
            "_label": "model-b",
            "ingestion.embedding": {
                "method": "api_embedding",
                "params": {"endpoint": "https://...", "model": "model-b"},
            },
            "ingestion.indexing": {
                "method": "elasticsearch",
                "params": {"hosts": "${ES_URL}", "index": "exp-model-b"},
            },
        },
    ],
}
```

`product` 模式下,整個 bundle 算一個維度參與交叉。

## 5. 接上評估指標

`run_experiments()` 回傳的每筆結果只有原始輸出,沒有分數。
接上框架內建的評估器就能算 hit_rate / MRR。

在 `scripts/` 底下開一個新檔(例如 `scripts/my_eval.py`):

```python
"""跑實驗並對每個組合算 hit_rate / MRR。"""

from experiment import run_experiments

from rag.evaluation import EvalCase, RetrievalMetricsEvaluator

# 標準答案:每題列出「應該被檢索到的文件 doc_id」。
# 注意:順序與內容必須對齊 experiment.py 的 QUERIES。
CASES = [
    EvalCase(query="FAISS 支援哪些索引結構?", relevant_doc_ids=["faiss.txt"]),
    EvalCase(query="Elasticsearch 的用途是什麼?", relevant_doc_ids=["elasticsearch.txt"]),
]

evaluator = RetrievalMetricsEvaluator(cases=CASES)
for rec in run_experiments():
    if rec["error"]:
        print(f"[FAIL] {rec['label']}: {rec['error']}")
        continue
    outputs = [output for _query, output in rec["results"]]
    metrics = evaluator.evaluate(CASES, outputs)["metrics"]
    print(f"{rec['label']:<45} hit_rate={metrics['hit_rate']:.3f}  mrr={metrics['mrr']:.3f}")
```

在 repo 根目錄執行 `python scripts/my_eval.py`,會看到每個組合一行分數:

```
baseline                                      hit_rate=1.000  mrr=1.000
retrieval=bm25                                hit_rate=1.000  mrr=0.750
...
```

`doc_id` 就是檔案相對於 `input_dir` 的路徑(例如 `manual.pdf`、
`sub/notes.md`)。

## 6. 保存結果與重現組合

每筆結果(record)都帶完整出處,可以存檔、之後重現:

| 欄位 | 內容 |
|---|---|
| `label` | 組合名稱(人讀的) |
| `overrides` | 這個組合改了哪些模組(相對於基底) |
| `config` | 完整的 config dict(`${ENV_VAR}` 保持原樣,金鑰不會被存進去) |
| `results` | 每題的 `query()` 完整輸出(documents / answer / trace…) |
| `error` | 失敗時的錯誤訊息,成功時是 `None` |

把勝出組合存成 YAML,之後就能直接當設定檔用:

```python
import yaml

best = max(records, key=my_score_function)
with open("configs/winner.yaml", "w", encoding="utf-8") as f:
    yaml.safe_dump(best["config"], f, allow_unicode=True)
```

```bash
python scripts/run_demo.py --config configs/winner.yaml
```

## 7. 注意事項

### a. 動到 ingestion 配置 + 用 Elasticsearch 時,每個組合要用不同的 index 名稱

**症狀**:比較不同 embedding 模型(或切塊參數)時,第二個組合報
dims 不符的錯,或結果混進了別的組合的資料。

**原因**:ES 的索引是持久的。兩個組合寫進同一個 index,資料會疊在一起;
而且 ES 的向量欄位維度(dims)建立後不能改,換了 embedding 模型再寫同
一個 index 會直接衝突。

**怎麼做**:用 bundle 把「要比較的 ingestion 設定」和「各自的 index 名稱」
綁在一起換(完整範例見第 4 節寫法四)。
或者更簡單:**實驗階段一律用 `indexing: in_memory`**,
不落地、跑完就消失,天生不會互相污染;選定組合後再上 ES。

### b. 實驗腳本預設把警告靜音了

**症狀**:接了真實 API 的組合分數異常地差,但終端機看不到任何錯誤。

**原因**:腳本頂部有一行 `logging.disable(logging.WARNING)`,
是為了讓掃描輸出乾淨。但它也吞掉了 fail-soft 降級警告
(例如 rerank API 掛掉時「保留原順序繼續跑」)——
流程跑完了,結果卻已經失真。

**怎麼做**:接真實 API 做實驗時,把那一行拿掉(或註解);
並且永遠檢查每筆結果的 `record["error"]`。

### c. 字串寫法只換 method,參數還是基底的

**症狀**:想比較「similarity 重排 top_k=5 vs top_k=10」,
但兩個組合結果一模一樣。

**原因**:字串寫法(如 `"similarity"`)只改 `method`,
參數一律沿用 `BASE_CONFIG` 的 `method_params` 型錄。

**怎麼做**:要比較參數,用 dict 寫法把參數寫進去:

```python
"inference.reranking": [
    {"method": "similarity", "params": {"top_k": 5}},
    {"method": "similarity", "params": {"top_k": 10}},
]
```

小提醒:dict 寫法的 label 只顯示方法名,上面兩個組合都會叫
`reranking=similarity`。要分得開,改用 bundle 寫法給 `_label`
(bundle 也可以只包一個模組)。

### d. 比較 llm_* 方法時,注意 LLM 從哪裡來

**症狀**:比較 `llm_rewrite` 有沒有效,結果和 baseline 完全一樣。

**原因**:`llm_rewrite` / `llm_decompose` / `insertrank` 這些方法沒指定
`generator` 時,沿用 generation 模組的 LLM。基底 `default.yaml` 的
generation 是 `mock`(假 LLM),假 LLM 的回覆解析不出來 →
fail-soft 退回原查詢,等於沒改寫(而且警告還被靜音了,見 b)。

**怎麼做**:在選項裡給這些方法一個真的 `generator`,
或給腳本化的 mock(指定 `replies` 讓它回固定 JSON)來做離線實驗。

### e. ingestion 相同的組合會共用索引(這是省時機制)

只比較 inference 端(檢索、重排、改寫)時,
所有組合的 ingestion 設定相同 → **索引只建一次**,之後每個組合直接查。
反過來說,每一種不同的 ingestion 設定 = 完整跑一次 ingest
(切塊 + embedding),語料大的時候要估一下時間。

### f. 在 repo 根目錄執行

`BASE_CONFIG` 與範例語料都是相對路徑,
請在 repo 根目錄跑 `python scripts/experiment.py`。
