# 次回セッション再開指示書（次回用・2026-10-15改定版）

**この指示書は2026-10-15作業終了時（SK 15:55日報確認後）に作成しました。次回司令塔AIと大久保本人の再開用です。**

### 参照した正本・コード一覧
- 記録・計画: `tasks/progress-20261015.md`、`tasks/prompts/_依頼文テンプレート.md`、`tasks/plan.md`、`tasks/todo.md`
- 実装コード: `app.py`、`manager/watcher.py`、`manager/watch_inbox.py`、`manager/pipeline_caller.py`
- 保存・再処理: `manager/ingest.py`、`manager/manager.py`、`manager/reprocess.py`
- 回帰テスト: `tests/test_manual_upload_store.py`、`tests/test_late_sidecar.py`

---

## 1. 確定事実と現状（2026-10-15終了時点）

- **PR #45マージ済み（main `6744440`）**:
  Web手動読み取り原画像の恒久保存（`images/`）、後着サイドカーJSONの機器名・真値反映、
  監視開始時競合を修正。全テスト215件成功（37.648秒メイン実測、次回の保証ではない）。
- **中間発表素材は完成済み**:
  スマホ撮影素材（大久保が実物温度計を撮影）を冒頭に含めた104.582秒の解説動画全体と
  PPTXスライド14枚（ノートあり）は埋め込み完了。撮り直し不要。想定11:45は配分見込みで声出し実測ではない。
- **SKくんの15:55日報（p1792047303612129）確認済み**:
  local demo mainは `6744440` へFF済み。手元枝 `feat/sk-04-guide-overlay` 作成済みだがコード未着手・未コミット。
  同期前 `cccf82a` でビルド成功実績あり（JBR 21.0.11環境）、`6744440` 後テスト未実行。実機adb未認識（要確認）。
- **SR・YM・KPの状況**:
  SR/YMは本日不在。KPは15:28時点で日報未回収。各自PCでの実動作は未確認。
  fetch後枝: YM `684575a` (95/0), SK `59a87ed` (151/4), SR `81c5e1c` (96/0), KP `f93e975` (110/3)。

## 2. 司令塔AIのオリエンテーションと行動規範

1. **外部記憶確認**: `C:\Obsidian_vault\Obsidian_vault\Claude\セッションルーター.md` を読み、
   `卒研/次にやること.md` と本日session記録を確認する。
2. **開始時照合**: `git status -sb` と `git fetch origin` を実行。
   Slack `#33-iot-ai-team-d` の最新日報・PRと照合し、前提差分を更新して未確認タスクのみを指示する。
3. **作業委任と保全**: 実装はOrcaの実CLI委任（Orca terminalで実CLI起動）。運用DB・画像・incomingを保全（隔離DB使用）。
   OCRは直列実行し、完了workerは速やかに解放する。
4. **PR・日報方針**: メンバーPRの採否判定は大久保本人が行う（**メンバーの作業を勝手にmergeしない**）。
   自分AIのPRは実測テストとレビュー解消後のみ。日報は固定8項目（実測コマンド・件数、未コミット表記）を徹底。
5. **凍結・禁止事項**: 自動送信（QueueSendWorker/HttpSender）本番結線、
   PCインストーラー、精度ロジック変更は勝手に開始しない。

## 3. 大久保本人の主作業

- Slack日報の回収と確認、メンバーPRの採否判定、各自ローカル環境の安全なmain同期指導。
- 発表スライド全14枚の声出し練習（時間計測）、および会場での動画再生・音声出力確認。

## 4. メンバー対応方針と配布プロンプト一覧

各プロンプトは `tasks/prompts/` に作成済み。未報告・未確認の場合にのみ配布する。
- **SKくん**: [SKくん-次回ガイド枠の継続確認-20261015.md](prompts/SKくん-次回ガイド枠の継続確認-20261015.md)
  既存枝再開、JBR21維持、短辺80%円枠目標、adb未認識時は合格扱いにせず未確認報告、固定8項目日報。
- **SRくん**: [SRくん-次回後着JSONの環境確認-20261015.md](prompts/SRくん-次回後着JSONの環境確認-20261015.md)
  PR #45後着JSON反映確認、`eval/images/meter2.jpg` 使用、inbox元画像保持、隔離DB、固定8項目日報。
- **YMさん**: [YMさん-次回原画像と再処理の確認-20261015.md](prompts/YMさん-次回原画像と再処理の確認-20261015.md)
  手動読み取り（`execute_pipeline`）原画像保存、SHA照合、再処理前後比較、meter4疑い修正禁止、固定8項目日報。
- **KPくん**: [KPくん-次回一覧とJSONLの結果確認-20261015.md](prompts/KPくん-次回一覧とJSONLの結果確認-20261015.md)
  一覧・JSONL実測、画面「記録番号」とJSONL「reading_id」の違い、突き合わせ基準、グラフ非連動記録、固定8項目日報。

## 5. 次回司令塔AIへの再開用貼り付けプロンプト（独立節）

次回セッション開始時に、司令塔AIへそのまま貼るプロンプト:

```text
あなたは卒業研究「アナログメーター自動読み取りシステム」の司令塔AIです。
正本URL: https://github.com/H3Y-dev/sotuken/blob/main/tasks/next-session-20261015.md
作業ディレクトリ: C:\卒研\git_stk\sotuken（dirty保全、未同期）
Vault router: C:\Obsidian_vault\Obsidian_vault\Claude\セッションルーター.md

【前提と確定事実】
- PR #45マージ済み（main 6744440）。全テスト215件成功（37.648秒実測）。
- スマホ撮影素材（温度計）を含む104.582秒の解説動画全体とPPTXスライド14枚完了。撮り直し不要。
- SKくんは15:55日報でmain FF6744440・既存枝 feat/sk-04-guide-overlay 作成済み、これからガイド枠実装。
- 自動送信結線、PCインストーラー、精度ロジック変更は凍結・着手禁止。メンバー作業の勝手なmerge禁止。

【最初にすること】
1. まずVault router（Claude\セッションルーター.md）と正本（卒研/次にやること.md、本日session記録）を読むこと（git操作より先）。
2. git status -sb と git fetch origin を実行して状態を確認。
3. Slack #33-iot-ai-team-d の最新日報とGitHub PRを確認し、進捗差分を照合。
4. 各自へ tasks/prompts/ 配下の次回用プロンプトを配布し、固定8項目日報を回収。
5. 大久保本人の主作業（日報確認、PR採否、発表スライド14枚の声出し練習、会場音声・動画再生確認）を支援してください。
```
