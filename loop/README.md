# メーター「目盛り推定」精度改善ループ

Evaluator-Optimizer パターン。生成者(Codex)と検証者(evaluate.py、決定的スクリプト)を分離。
2026-08-29、対象を目盛り(スケール)推定アルゴリズムに絞り込み、目視確認ステップを追加した。

- 設計: Claude(このディレクトリ一式) / 生成: Codex (`gpt-5.6-terra`, CLI直叩き) / 検証: `evaluate.py` + `check_exit.py`
- 対象範囲: `tick_detect.py` / `scale_value_detect.py`(目盛り検出・スケール範囲推定)のみ。
  中心推定・OCR・VLMは対象外(担当が別、または既に改善済み)
- 詳細設定: `config.env`

## ガードレール(確定値)

| # | 項目 | 値 |
|---|---|---|
| 1 | 終了条件(数値) | `summary.mean_reference_error < 1.0` (`--scope round`9枚、2026-08-29実測ベースライン1.37%FSからの改善) |
| 2 | 最大反復回数 | 5 |
| 3 | 予算上限 | 反復回数(5)で実質制御。形式チェックのみ |
| 4 | サンドボックス | `git worktree` (`../sotuken-loop`, branch `loop/meter-accuracy`) |
| 5 | 人間チェックポイント | mainへの反映(マージ)はしない。ユーザーが手動で確認・マージ |
| 6 | **目視確認(新設)** | 数値PASS(またはMAX_ITERS到達)のたびに `tools_render_overlays.py` でオーバーレイ画像を自動生成する。**マージ前に必ず人(Claude/本人)が目視確認すること。** 数値だけでの合否判定はしない([[恒久指示]]3章) |

## なぜ数値閾値だけでは不十分か

過去に「引用誤差0.11%FSで最優秀」と評価していた画像が、実際にはスケール最大値を
誤検出し、たまたま針が0付近を指していたため誤差に現れなかった実例がある
(`tools_render_overlays.py`のdocstring参照)。目盛り推定の改善はこの種の
「条件次第で表面化する不具合」を生みやすいため、数値PASSは「マージしてよい」の
合図ではなく「目視確認の対象ができた」の合図として扱う。

## 実行方法

Git Bash (このリポジトリは `C:\卒研\git_stk\sotuken`) で:

```bash
cd "C:/卒研/git_stk/sotuken"

# 1. 初回のみ: サンドボックス(worktree)を作成
bash loop/setup_worktree.sh

# 2. ループ実行(最大5ラウンド、達成 or 上限で自動停止)
bash loop/run_loop.sh
```

- 途中で止めたい場合は単純に Ctrl+C。ラウンドの区切りごとにしか進まないので、
  実行中のCodex呼び出しが終わるまでは止まらない。
- 各ラウンドのプロンプト・Codexログ・evaluate.pyログ・判定結果は
  `loop/runs/<timestamp>/` に保存される。
- worktree (`../sotuken-loop`) 側では、ラウンドごとに進捗コミットが積まれる
  (`loop: round N 試行 (...)` / 達成時は `loop: round N で目標達成 (...)`)。
  これは **mainには一切影響しない**。

## 終了後にやること(人間チェックポイント)

1. `loop: round N で目標達成` のコミットで止まった場合:
   ```bash
   cd "C:/卒研/git_stk/sotuken-loop"
   git log --oneline -10          # 変更内容を確認
   git diff main...HEAD -- tick_detect.py scale_value_detect.py meter_pipeline.py
   ```
2. **`sotuken-loop/eval/overlays_loop_round<N>/`(worktree側)の画像を必ず目視確認する。**
   見るべき点は各画像左上のテキスト(検出したスケール範囲)とマゼンタの点(主目盛り)が
   実際の目盛り線の上に乗っているか(`tools_render_overlays.py`のdocstring参照)。
   特に、対象だった気密試験_昇圧後圧力計(0-108→0-150の誤検出)が直っているか確認する。
3. 確認結果を `卒研/検証画像/<YYYY-MM-DD>_目盛り推定ループ/` にコピーし、何を見て何が
   確認できたかを書いたREADMEを添える(恒久指示6章)。
4. 内容を確認したうえで、必要なら手動で `main` にチェリーピック/マージする。
   このループはmainへのpush/mergeを一切行わない。

2. `MAX_ITERS` に到達して未達成の場合(exit code 3):
   - `loop/runs/<最新>/verdict_round5.txt` で最終スコアを確認。
   - 改善傾向があれば `THRESHOLD` を緩めて再実行するか、`generator_prompt.md` の
     指示を調整して再度 `bash loop/run_loop.sh` を実行する
     (worktreeとブランチは使い回されるので、Codexの前回セッション履歴は失われるが
     コード変更は引き継がれる)。

## 概算コスト

- Codex呼び出し: ChatGPT Plus月額内(API従量課金なし)。1ラウンドあたり数分〜十数分程度。
- Claude側: このスキャフォールド作成のみで、ループ実行自体はClaudeの利用枠を消費しない
  (`run_loop.sh` はbashスクリプトとして独立に動く)。
- どのガードレールが最初に発動するか: 通常は **MAX_ITERS=5** (5ラウンドで未達なら停止)。
  BUDGET_ITERSはMAX_ITERSと同値にしてあるため実質同時に発動する。

## ファイル一覧

- `config.env` — 全設定値(閾値・上限・パス)
- `setup_worktree.sh` — サンドボックス(git worktree)作成
- `run_loop.sh` — ループ本体(生成→検証→判定→次ラウンド)
- `generator_prompt.md` — Codexへ渡すプロンプトのテンプレート
- `check_exit.py` — report.jsonを閾値と比較する決定的な検証ロジック
- `runs/` — 実行ログ(gitignore推奨、下記参照)
