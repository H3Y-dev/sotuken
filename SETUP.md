# セットアップ手順（VSCode + Python）

`main_sotuken.py`（アナログメーター角度検出・数値変換プログラム）を動かすために必要な
ライブラリ・Ollama・Qwen3-VLモデルのインストール方法をまとめたものです。
Windows環境を前提としています。

## 前提条件

- Python 3.8系（このプロジェクトの`venv`は3.8.8で作成済み）
- VSCode + Python拡張機能がインストール済み
- インターネット接続（モデルダウンロードに数GB必要）

---

## 1. Python仮想環境（venv）のセットアップ

このプロジェクトには既に`venv`フォルダが用意されています。まだ無い場合は作成してください。

```powershell
# プロジェクトフォルダで実行
python -m venv venv
```

### VSCodeでこのvenvを使うように設定する

1. VSCodeでコマンドパレットを開く（`Ctrl+Shift+P`）
2. `Python: Select Interpreter` を選択
3. `.\venv\Scripts\python.exe` を選択
   （一覧に出てこない場合は「Enter interpreter path...」から直接パスを指定）

以降、ターミナルやデバッグ実行がこのvenv上のPythonを使うようになります。

---

## 2. 必要なPythonライブラリのインストール

`requirements.txt`にまとまっているので、venvを有効化してからインストールします。

```powershell
# venvを有効化（PowerShellの場合）
.\venv\Scripts\Activate.ps1

# ライブラリをインストール
python -m pip install -r requirements.txt
```

`requirements.txt`の内容：

| パッケージ | 用途 |
|---|---|
| opencv-contrib-python | 画像処理全般（目盛り線検出、中心検出など） |
| numpy | 数値計算 |
| pillow | 画像の読み込み・GUI表示 |
| pytesseract | （現在は`ocr_meter.py`という旧スクリプト専用。メインの`main_sotuken.py`では未使用） |
| rapidocr, onnxruntime | 盤面の数字のOCR読み取り |
| ollama | VLM（Qwen3-VL）と通信するためのクライアント |

> `pytesseract`はPythonパッケージを入れただけでは動かず、別途Tesseract-OCR本体のインストールが必要です。ただし現在のメインアプリでは使用していないため、`ocr_meter.py`を使う予定が無ければスキップして構いません。
> （必要な場合のみ: https://github.com/UB-Mannheim/tesseract/wiki からWindows版をインストール）

---

## 3. Ollamaのインストール

VLM（Qwen3-VL）を動かすためのランタイムです。

1. https://ollama.com/download からWindows版をダウンロードしてインストール
2. インストール後、タスクトレイに常駐し、バックグラウンドでOllamaサーバーが自動起動します
3. インストール確認：

```powershell
ollama --version
```

**バージョン0.12.7以上が必要です**（Qwen3-VLの動作要件）。古い場合はOllamaを再インストールするか、公式サイトから最新版を入れ直してください。

---

## 4. Qwen3-VLモデルの取得

```powershell
ollama pull qwen3-vl:8b
```

- ダウンロードサイズ：約6.1GB
- 8Bモデルで、通常のノートPC（GPU無しでも動作、GPUがあれば高速化）を想定したサイズです
- 取得できたか確認：

```powershell
ollama list
```

`qwen3-vl:8b`が表示されていればOKです。

### 動作確認（任意）

```powershell
ollama run qwen3-vl:8b "こんにちは"
```

何かしら応答が返ってくればセットアップ完了です（`Ctrl+D`または`/bye`で終了）。

---

## 5. アプリの実行

VSCodeのターミナル（venvが有効化されている状態）で：

```powershell
python main_sotuken.py
```

GUIウィンドウが開けば起動成功です。「画像を開く」から解析したいメーター画像を選択してください。

---

## トラブルシューティング

- **`ollama`コマンドが見つからない**：インストール後にターミナル（VSCode含む）を再起動してください（PATHの反映のため）
- **VLM関連の処理がエラーになる/固まる**：タスクトレイでOllamaが起動しているか確認してください。`ollama list`がエラーなく実行できればサーバーは動いています
- **`pip install`でエラーが出る**：venvが有効化されているか（プロンプトの先頭に`(venv)`と出るか）を確認してください。有効化されていない場合、正しいPythonにインストールされず`main_sotuken.py`実行時に`ModuleNotFoundError`になります
- **RapidOCRの初回実行が遅い**：初回のみ内部でモデルファイルをダウンロード/検証するため時間がかかります。2回目以降は速くなります
