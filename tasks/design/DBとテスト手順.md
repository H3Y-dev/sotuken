# DBとテスト手順

本ドキュメントは、本リポジトリにおける **3つのDBの使い分け・安全な初期化手順** および **標準テスト手順（単体テスト / メインデータセット評価 / React Web 6画面通し確認）** をまとめた運用ガイドです。

---

## 1. 3つのDBの使い分けと安全な初期化・リセット手順

### 1.1 DBの種類と役割

| DB種別 | 主なパス / 生成方法 | 用途 | Git管理 |
|---|---|---|---|
| **本番DB** | `manager.db`（既定のSQLiteファイル） | 実運用・手動確認用の機器台帳・点検記録 | **対象外**（`.gitignore`） |
| **デモDB** | `tools/make_demo_db.py` で生成 | 発表・画面確認用のサンプルデータ入りDB | **対象外**（生成物） |
| **評価用一時DB・レポート** | `tempfile` / `eval/report_*.json` | `evaluate.py` や `tools/eval_front_main.py` の一時評価・結果出力 | **対象外**（一時ファイル・レポート） |

### 1.2 安全な初期化・リセット手順

1. **バックアップの取得**
   本番DB `manager.db` をリセットする前に、必ず別名でバックアップを取ります。
   ```powershell
   Copy-Item manager.db "manager.db.bak_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
   ```
2. **画像・オーバーレイディレクトリの扱い**
   - `incoming/`: 取り込み待ち画像の一時置き場。処理後は空または退避済みであることを確認する。
   - `images/`: 登録済み点検画像の実体。DBと整合するため、DBを初期化する場合は必要に応じて退避・削除する。
   - `overlays/`: パイプラインが生成する確認用オーバーレイ画像。再生成可能なため、クリーンアップ対象にしてよい。
3. **デモDBの再作成**
   ```powershell
   .\venv\Scripts\python.exe tools\make_demo_db.py
   ```
4. **企業提供画像に関する注意**
   - `企業提供_日本製鋼所` などの企業提供実写画像は **絶対にGitリポジトリへコミットしない** でください（ローカルの `C:\卒研\サンプルメーター（本番用）\` 等に配置して参照する）。

---

## 2. 標準テスト手順

### 2.1 単体テスト

変更範囲に応じて、以下の単体テストを実行します。

- **Python (`unittest`)**
  ```powershell
  .\venv\Scripts\python.exe -m unittest discover -s tests -v
  ```
  個別実行例:
  ```powershell
  .\venv\Scripts\python.exe -m unittest tests/test_eval_front_main.py -v
  ```

- **React Web (`prototypes/react-records`)**
  ```powershell
  cd prototypes/react-records
  npm run test        # vitest
  npm run lint        # oxlint
  npm run build:static
  ```

- **Android (`android-app` 等)**
  ```powershell
  .\gradlew.bat testDebugUnitTest
  ```

### 2.2 メインデータセット（正面3D QR付き＋企業提供JSW）のチェック手順

1. **QRデコード & `eval/devices.csv` 整合性チェック（高速・OCRなし）**
   ```powershell
   .\venv\Scripts\python.exe tools\eval_front_main.py --check-qr-only
   ```
   - 期待結果: `[3D正面] total=60, qr_ok=60/60, device_id_match=60/60` および `[JSW] total=4, devices_csv_ok=4/4`

2. **パイプライン評価の実行（`--no-vlm`）**
   ```powershell
   .\venv\Scripts\python.exe tools\eval_front_main.py --evaluate --no-vlm --report eval\report_front_main.json
   ```
   - 3D正面・JSWそれぞれの `read_ok`, `±2.5%FS`, `±5.0%FS`, `mean/median/max %FS` がグループ別に出力されます。

### 2.3 React Web 6画面の通し確認手順

1. **サーバー起動**
   ```powershell
   .\venv\Scripts\python.exe -m pc_api.launcher
   ```
   ブラウザで `http://127.0.0.1:8766` を開きます。

2. **6画面の順次確認**
   1. **機器登録**: 新規機器の登録・一覧表示・編集ができること
   2. **ルート**: 点検ルートの作成・機器の割り当てができること
   3. **接続・設定**: API接続状態・設定値の確認と保存ができること
   4. **点検確認**: 取り込み済み点検画像の読み取り結果・オーバーレイが確認できること
   5. **CSV**: 点検結果のCSVエクスポートが正常にダウンロードできること
   6. **手動読み取り**: 画像をアップロードして手動で読み取り・補正・確定ができること
