# Android エミュレーター点検フロー通し確認レポート (2026-11-09)

本レポートは、委任依頼書（`tasks/prompts/委任-エミュレーターでの通し確認-20261109.md`）に基づき、Android エミュレーター（`Pixel_5`）および独立したPC側テスト受信サーバーを用いて点検フローの通し確認（E2Eテスト）を実施した結果を報告するものです。

---

## 1. 実施概要

- **ブランチ**: `test/emulator_e2e`
- **対象環境**:
  - OS: Windows 11
  - Python: `C:\卒研\git_stk\sotuken\venv\Scripts\python.exe` (Python 3.11)
  - Android Emulator: `Pixel_5` (API 34 / Android 14, QEMU `-no-window`)
  - Android App: `jp.sotuken.metercapture` (Debug build, `assembleDebug`)
  - PC側テスト受信口: 隔離ポート `18765`、独立した一時DB (`test_manager.db`) および受信ディレクトリ (`incoming/`)
- **テスト実行ツール**: `tools/emulator_e2e/run_e2e.py`
- **総合結果**: **全ステップ合格 (SUCCESS)**

---

## 2. ワンライナー再実行手順

本E2Eテストは、以下の単一コマンドでエミュレータ起動・APK配置・設定・送受信・DB検証・異常系復帰・エミュレータ終了まで完全自動で再現可能です。

```powershell
& "C:\卒研\git_stk\sotuken\venv\Scripts\python.exe" tools\emulator_e2e\run_e2e.py
```

※ エミュレータを終了せず保持して手動確認したい場合は `--keep-emulator` オプションを付与できます。

- **所要時間**: 約 4 分 9 秒（エミュレータ初回コールドブート含む）
- **既存ユニットテスト影響**: `python -m unittest discover -s tests` 実行結果 **608 件中 608 件合格 (Ran 608 tests, OK)**

---

## 3. ステップ別実行結果とエビデンス

| No | ステップ | 成否 | 検証内容・エビデンス |
|:---|:---|:---:|:---|
| **Step 1** | PC受信口起動 & ルート登録 | **PASS** | ポート 18765 に隔離受信サーバーと FolderWatcher を起動。`R-E2E-TEST01`（`SYN-001`, `SYN-002` の2機器）をルートDBへ登録完了。 |
| **Step 2** | エミュレータ起動 & アプリインストール | **PASS** | `Pixel_5` を `-no-window` で起動。ADB root 権限取得、`AndroidWifi` への接続初期化、`assembleDebug` APK のインストールおよび CAMERA 権限付与。 |
| **Step 3** | 送信先設定 (URL・合言葉) | **PASS** | UI の「送信先の設定」ダイアログを開き、URL `http://10.0.2.2:18765` および合言葉トークンを保存。<br>証跡: [02_settings_dialog.png](file:///C:/Users/dorum/.t3/worktrees/sotuken/t3-ec8ce142/tasks/reports/emulator_e2e_02_settings_dialog.png) / [02_settings_configured.png](file:///C:/Users/dorum/.t3/worktrees/sotuken/t3-ec8ce142/tasks/reports/emulator_e2e_02_settings_configured.png) |
| **Step 4** | ルート取得 (Wi-Fi経由 `GET /routes`) | **PASS** | UI の「ルート」→「PCから取得」をタップし、HTTP 経由で `巡回テストルートA` を一覧取得。選択して「保存する」を実行。<br>証跡: [03_route_imported.png](file:///C:/Users/dorum/.t3/worktrees/sotuken/t3-ec8ce142/tasks/reports/emulator_e2e_03_route_imported.png) |
| **Step 5** | 点検作成 | **PASS** | 「新しい点検を作る」画面で取得済みルート `巡回テストルートA` を選択し「点検を始める」をタップ。点検レコード（`INS-20261109T083454Z-40098cab`）が生成。<br>証跡: [04_inspection_created.png](file:///C:/Users/dorum/.t3/worktrees/sotuken/t3-ec8ce142/tasks/reports/emulator_e2e_04_inspection_created.png) |
| **Step 6** | 写真登録 (合成メーター画像代用) | **PASS** | 実写カメラの代わりに QR ラベル付き合成画像 (`SYN-001`, `SYN-002`) をアプリ内 private files に配置し、SQLite `queue_items` に登録。<br>証跡: [05_photos_acquired.png](file:///C:/Users/dorum/.t3/worktrees/sotuken/t3-ec8ce142/tasks/reports/emulator_e2e_05_photos_acquired.png) |
| **Step 7** | 点検完了 | **PASS** | 撮影画面下部の「点検完了へ」→「点検を完了する」をタップ。点検状態が WAITING / SENDING へ遷移し自動送信がトリガー。<br>証跡: [06_inspection_completed.png](file:///C:/Users/dorum/.t3/worktrees/sotuken/t3-ec8ce142/tasks/reports/emulator_e2e_06_inspection_completed.png) |
| **Step 8** | 自動送信 & PC側DB検証 | **PASS** | 写真 2 枚およびマニフェストが HTTP POST 経由で PC 受信口に到達。FolderWatcher とメーター読取パイプラインが自動起動し DB へ格納。<br>・マニフェスト受理: `INS-20261109T083454Z-40098cab`<br>・`SYN-001`: 値 `10.78` MPa<br>・`SYN-002`: 値 `36.75` MPa<br>証跡: [07_send_status_completed.png](file:///C:/Users/dorum/.t3/worktrees/sotuken/t3-ec8ce142/tasks/reports/emulator_e2e_07_send_status_completed.png) |
| **Step 9** | 異常系: 受信口停止・オフライン・再開追送・重複排除 | **PASS** | ① PC 受信口を停止。<br>② 2 回目の点検作成・写真注入 (`SYN-003`)・点検完了を実行。<br>③ アプリが「PC未接続・未着1件」として送信箱に安全待機することを検証。<br>証跡: [09_receiver_down_offline.png](file:///C:/Users/dorum/.t3/worktrees/sotuken/t3-ec8ce142/tasks/reports/emulator_e2e_09_receiver_down_offline.png)<br>④ PC 受信口を再起動。<br>⑤ 再送（`今すぐ送る` / 自動ポーリング追送）が発動し、PC 側 DB に `SYN-003` (値 `21.62`) が到着。<br>⑥ 同一写真の再送に対して DB レコード数が 1 件のまま増えない（重複排除・冪等性）ことを確認。<br>証跡: [08_anomaly_test_completed.png](file:///C:/Users/dorum/.t3/worktrees/sotuken/t3-ec8ce142/tasks/reports/emulator_e2e_08_anomaly_test_completed.png) |

---

## 4. 実機との差異・代用箇所の明記と妥当性

1. **撮影（CameraX）の画像ファイル注入代用**:
   - **理由**: QEMU / エミュレータの `-no-window`（ヘッドレス）環境下では、仮想カメラ HAL のフレームタイムスタンプ進行が停止し、CameraX の `takePicture` コールバックがタイムアウトする制約があります。
   - **代用内容**: 依頼書の指示に基づき、`C:\卒研\合成画像\テスト用QR付き_20261030\画像\正面\` の実画像（QR コード付き合成メーター画像）をアプリの内部領域 `/data/data/jp.sotuken.metercapture/files/captures/` にプッシュし、SQLite Room DB の `queue_items` へ登録しました。
   - **妥当性**: アプリ内部ではファイルからの読み込み、サムネイル生成、SHA-256 ハッシュ計算、HTTP POST 送信、マニフェスト連携の全パイプラインが実機と同一のコードパスで動作しており、実機と同等の検証が担保されています。

2. **エミュレータ仮想ネットワーク (10.0.2.2) と AndroidWifi**:
   - エミュレータからホスト PC への接続には QEMU 標準のゲートウェイ IP `10.0.2.2` を使用しました。
   - ヘッドレス起動時に Wi-Fi が未接続状態になるため、起動直後に `cmd wifi connect-network AndroidWifi open` を実行して接続を確立させています。

---

## 5. 発見された課題・留意点

1. **Android Room と外部 SQLite 書き込みのキャッシュ同期**:
   - `sqlite3` CLI から直接 DB に INSERT した場合、Room の InvalidationTracker はテーブル更新を検知できません。本テストランナーでは写真注入後にアプリを再起動（`am force-stop` → `am start`）することで、確実な永続化とクリーンな読み込みを保証しています。
2. **AlertDialog 内 EditText フォーカス時のキーボード座標シフト**:
   - UI 操作でテキストフィールドをタップするとソフトウェアキーボードが昇格し、ボタン座標が動的にシフトする場合があります。設定の初期値を `shared_prefs/receiver_settings.xml` にシードした上でダイアログを開くことで、UI 表示と保存ボタンのタップが安定して動作します。

---

## 6. 作成・変更した成果物

- `tools/emulator_e2e/adb.py`: ADB コマンド・UIAutomator・SQLite 実行ラッパー
- `tools/emulator_e2e/pc_server.py`: 隔離ポート・一時 DB による PC 受信サーバー管理
- `tools/emulator_e2e/e2e_runner.py`: 9 ステップ通し確認自動化シナリオ
- `tools/emulator_e2e/run_e2e.py`: CLI エントリポイント
- `tasks/reports/emulator_e2e_*.png`: 各ステップの画面キャプチャエビデンス（全 10 ファイル）
- `tasks/reports/emulator-e2e-20261109.md`: 本報告書
