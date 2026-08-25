# セットアップ手順（VSCode + Python）

`main_sotuken.py`（アナログメーター角度検出・数値変換プログラム）を動かすために必要な
ライブラリ・Ollama・Qwen3-VLモデルのインストール方法をまとめたものです。
Windows環境を前提としています。

## 前提条件

- Python 3.8系（このプロジェクトの`venv`は3.8.8で作成済み）
- VSCode + Python拡張機能がインストール済み
- インターネット接続（モデルダウンロードに数GB必要）

---

## 0. リポジトリをclone する

```powershell
git clone https://github.com/H3Y-dev/sotuken.git
cd sotuken
```

`venv`フォルダは`.gitignore`で除外されており、cloneした直後は**存在しません。**
次のステップで新規に作成してください（「他の人が作ったvenvが見当たらない」は
正常な状態です。gitはvenv自体をリポジトリに含めない設計になっています）。

---

## 1. Python仮想環境（venv）のセットアップ

**先にPython 3.8系が入っているか確認してください。** PCに複数のPythonバージョンが
入っていることがあり、`python`コマンドが3.8以外（3.11や3.14等）を指してしまう場合が
あります。バージョンがズレると、`requirements.txt`のバージョン固定パッケージが
インストールできず失敗します。

```powershell
# インストール済みのPythonバージョン一覧を確認
py -0
```

一覧に`3.8`が無い場合は、事前に[python.org](https://www.python.org/downloads/release/python-388/)
等からPython 3.8系をインストールしてください。

```powershell
# プロジェクトフォルダ（sotuken）の直下で実行
# "python" ではなく "py -3.8" を使い、バージョンを明示的に指定する
py -3.8 -m venv venv
```

> [!warning]
> **Anacondaが唯一の3.8として登録されている環境では、`sqlite3`が使えません**
> （T6の保存層で使用）。`py -0p`で一覧を見たとき、3.8の行が
> `C:\Users\<ユーザー名>\anaconda3\python.exe`を指している場合が該当します。
> Anacondaは`import sqlite3`に必要な`sqlite3.dll`を`Library\bin`にしか
> 置いておらず、`conda activate`で環境を有効化しない限りそこがPATHに
> 乗らないため、`py -3.8`や通常のvenvから直接呼ぶと次のエラーで失敗します。
> ```
> ImportError: DLL load failed while importing _sqlite3: 指定されたモジュールが見つかりません。
> ```
> **直し方（1回だけでOK、Anaconda本体に対して行う）:**
> ```powershell
> Copy-Item "C:\Users\<ユーザー名>\anaconda3\Library\bin\sqlite3.dll" `
>           "C:\Users\<ユーザー名>\anaconda3\DLLs\sqlite3.dll"
> ```
> このあと`py -3.8 -c "import sqlite3; print(sqlite3.sqlite_version)"`が
> 通ればOKです。**既にvenvを作ってしまっている場合は、上記コピーの後に
> venvを作り直す必要はありません**（venvはシステムのDLL検索を使うため、
> このコピーだけで既存venvも直ります）。

`venv`フォルダがこのプロジェクト専用に新しく作られます。他のプロジェクトの
venvと混ざることはありません。作成後、念のためバージョンを確認してください。

```powershell
.\venv\Scripts\python.exe --version
# Python 3.8.x と表示されればOK
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

# rapidocrが依存関係として opencv-python を引き込んでしまい、
# 既に入れた opencv-contrib-python と衝突する(cv2の挙動がおかしくなり
# main_sotuken.pyの針検出が壊れる)。以下の2行で必ず解消しておく。
python -m pip uninstall -y opencv-python
python -m pip install --force-reinstall --no-deps opencv-contrib-python==4.10.0.84
```

> [!warning]
> `opencv-python`と`opencv-contrib-python`は同じ`cv2`という名前を提供する別パッケージで、
> **両方入っていると片方の中身で上書きされ、原因不明のエラー（`cannot unpack non-iterable
> numpy.int32 object`等）が出ます。** 上記2行を忘れると、`python -m unittest discover -s tests`
> がエラーになります。心当たりのないエラーが出たら、まず`pip list`で両方入っていないか確認してください。

`requirements.txt`の内容：

| パッケージ | 用途 |
|---|---|
| opencv-contrib-python | 画像処理全般（目盛り線検出、中心検出など） |
| numpy | 数値計算（中心推定の円フィッティング等も含む） |
| pillow | 画像の読み込み・GUI表示 |
| rapidocr, onnxruntime | 盤面の数字のOCR読み取り |
| ollama | VLM（Qwen3-VL）と通信するためのクライアント |
| streamlit, pandas | T6一元管理システムのWeb UI（`app.py`） |

> [!note] streamlit / pandas のバージョンについて
> `streamlit==1.40.1` / `pandas==2.0.3` は **Python 3.8に対応する最終版**です。
> これより新しい版はPython 3.9以上が必須になるため、上げないでください。
> 既存の`numpy==1.24.4` / `pillow==10.4.0`と衝突しないことは確認済みです。
>
> `app.py`（T6のWeb UI）を使わない場合、この2つは無くても
> `main_sotuken.py`の動作には影響しません。

> 旧スクリプト（`ocr_meter.py`, `paddletest.py`）専用の依存関係（`pytesseract`等）は
> 現行パイプラインでは使わないため`requirements.txt`から外してあります。これらの
> スクリプトを使う予定がなければ気にしなくて大丈夫です。

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
ollama pull qwen3-vl:4b-instruct
```

- ダウンロードサイズ：約3.3GB
- 4Bモデルで、通常のノートPC（GPU無しでも動作、GPUがあれば高速化）を想定したサイズです
- `-instruct`は思考プロセスを持たない版です。通常版（`qwen3-vl:8b`等）は回答前に内部推論トークンを消費するため応答が数倍遅くなります
- 取得できたか確認：

```powershell
ollama list
```

`qwen3-vl:4b-instruct`が表示されていればOKです。

### 動作確認（任意）

```powershell
ollama run qwen3-vl:4b-instruct "こんにちは"
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

### 「Ollamaをインストールしたのに、VSCodeのターミナルで`ollama`コマンドが見つからない」

Windowsでは、インストーラーがPATH環境変数を更新しても、**既に開いているターミナルやアプリはその変更を認識しません**（新しく起動したプロセスにしか反映されない）。インストール後にVSCodeを開きっぱなしにしていた場合によく起こります。上から順に試してください。

1. **VSCode内のターミナルタブを閉じて、新しく開き直す**
   ターミナルパネルのゴミ箱アイコンで閉じて、「+」で新規ターミナルを開く。これで直ることが多いです。

2. **それでも直らなければ、VSCodeを完全に終了して開き直す**
   「ウィンドウの再読み込み」ではなく、VSCodeアプリ自体を終了（×で閉じる、またはタスクバーから終了）してから再起動してください。VSCode自体もPATHを起動時にしか読み込みません。

3. **それでも直らなければ、PATHに本当に登録されているか確認する**
   PowerShellターミナルで実行：
   ```powershell
   [Environment]::GetEnvironmentVariable("Path", "User") -split ";" | Select-String -Pattern "Ollama"
   ```
   何も表示されない場合、PATHに登録されていません。以下の手順で手動追加してください：
   - Windowsキー→「環境変数を編集」と検索して開く
   - 「ユーザー環境変数」の`Path`を選択→「編集」→「新規」
   - `%LOCALAPPDATA%\Programs\Ollama`（通常は`C:\Users\<ユーザー名>\AppData\Local\Programs\Ollama`）を追加してOK
   - PC（またはWindowsへのログイン）を再起動して反映させる

4. **最終手段：Windowsを再起動する**
   まれにログインセッション全体の環境変数キャッシュが原因のことがあります。

### 「`ollama run`で"CUDA error: device kernel image is invalid"というエラーが出る」

```
Error: 500 Internal Server Error: llama-server process has terminated: exit status 0xc0000409...: CUDA error
CUDA error: device kernel image is invalid
```

このエラーはPythonコード側の問題ではなく、**GPUの世代とOllamaに同梱されているCUDAカーネルの互換性問題**です。GPUドライバが古い、またはGPUのアーキテクチャがOllamaの対応範囲外の場合に発生します。

1. **まずNVIDIAドライバを最新版に更新する**（最も多い原因）
   [NVIDIA公式サイト](https://www.nvidia.com/Download/index.aspx)から最新ドライバを入れてPCを再起動し、再度試す

2. **それでも直らない場合は、CPUのみで動かす（回避策）**
   処理は遅くなりますが動作はします。PowerShellで環境変数を設定：
   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_LLM_LIBRARY", "cpu", "User")
   ```
   設定後、タスクトレイのOllamaを完全に終了してから再起動（またはPC再起動）し、再度試してください。

3. GPUの世代が古すぎる/新しすぎる等で根本的に非対応の場合、2のCPUモードが唯一の回避策になります

### その他

- **VLM関連の処理がエラーになる/固まる**：タスクトレイでOllamaが起動しているか確認してください。`ollama list`がエラーなく実行できればサーバーは動いています
- **`pip install`でエラーが出る**：venvが有効化されているか（プロンプトの先頭に`(venv)`と出るか）を確認してください。有効化されていない場合、正しいPythonにインストールされず`main_sotuken.py`実行時に`ModuleNotFoundError`になります
- **RapidOCRの初回実行が遅い**：初回のみ内部でモデルファイルをダウンロード/検証するため時間がかかります。2回目以降は速くなります
