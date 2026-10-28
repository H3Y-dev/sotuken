# 工程別評価ツール (Stage Errors Evaluation)

合成画像・実画像データセットに対して、各処理工程（盤面中心、0点・満尺点目盛り、目盛り範囲、針検出）ごとの誤差を逐次記録・集計するためのスクリプト群です。

## 構成
- `eval/stage_errors.py`: 画像ごとの工程別誤差を計算し、1行ずつJSONL形式で出力・フラッシュする評価実行スクリプト。中断時の再開（レジューム）対応。
- `eval/summarize_stage.py`: `stage_errors.py` が出力したJSONLファイルを読み込み、条件別・工程別の集計表およびワースト症例をMarkdown形式で標準出力に表示するスクリプト。
- `tests/test_stage_errors.py`: 各種幾何計算・誤差集計・再開ロジックの単体テスト。

## 使い方

リポジトリルート（`C:\卒研\git_stk\sotuken` 等）から実行します。

### 1. 誤差評価の実行
```bash
python eval/stage_errors.py <正解JSONパス> -o <出力先JSONLパス> [オプション]
```

主なオプション:
- `-o, --output PATH`: 出力先JSONLファイルパス（必須）
- `--local-read`: 局所読み取り方式を使用する（既定: 全体読み取り）
- `--needle-angle {segment,tip}`: 針の角度算出元（既定: segment）
- `--limit N`: 先頭 N 件のみを評価（中断・再開時は完了分を含めてカウント）

※ `meter_pipeline.read_meter` は常に `use_vlm=False`（再現性確保のため）で実行されます。
※ 処理中に例外が発生した場合もプロセスは停止せず、該当行に `error` を記録して次の画像へ進みます。

### 2. 集計結果の確認（Markdown出力）
```bash
python eval/summarize_stage.py <出力先JSONLパス>
```
標準出力に、条件別集計表（ALL、メーター種類、カメラ画角、照明、ボケ）、工程別内訳、および引用誤差（%FS）のワースト症例がMarkdown表として出力されます。
