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

# 先にpipを新しくする。venvを作った直後のpipは古く(20.2.3)、
# requirements.txtの日本語コメントをcp932で読もうとして
# UnicodeDecodeError で失敗することがある
python -m pip install --upgrade pip

# ライブラリをインストール
python -m pip install -r requirements.txt
```

> [!note] opencvのバージョンについて（2026-09-08、手動手順は不要になりました）
> `rapidocr` が `opencv-python` をバージョン指定なしで依存に持つため、放っておくと
> **opencv-python 5系が後から入って `cv2` の中身が上書きされます。**
> その状態では `HoughLinesP` の戻り値の形が変わり、`meter_reader.detect_needle` が
> `TypeError: cannot unpack non-iterable numpy.int32` で落ちます。
>
> 以前はここに `opencv-python` をアンインストールする手順を書いていましたが、
> **`requirements.txt` に `opencv-python==4.10.0.84` のピンを追加したので不要になりました。**
> `pip install -r requirements.txt` だけで正しい版に固定されます。
>
> インストール後、次で確認できます。**`4.10.0` と出れば正常です。**
> ```powershell
> .\venv\Scripts\python.exe -c "import cv2; print(cv2.__version__)"
> ```
> `5.0.0` と出た場合は、ピンが入る前の古い `requirements.txt` を使っています。
> `git pull` してから入れ直してください。

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

### Web UI（`app.py`）の起動

```
venv\Scripts\python.exe -m streamlit run app.py
```

ブラウザが開きます（開かない場合は `http://localhost:8501`）。停止は `Ctrl+C`。

> [!important] 初回起動でメールアドレスの入力を求められたら
> Streamlitは初回に `Email:` と聞いてきて、**入力待ちのまま止まります。**
> 起動しないように見えるので、先に次のファイルを作っておいてください。
>
> **`C:\Users\<ユーザー名>\.streamlit\credentials.toml`**
>
> ```toml
> [general]
> email = ""
> ```
>
> **リポジトリ内の `.streamlit/` に置いても効きません。** Streamlitは
> `credentials.toml` だけはホームディレクトリのものしか読まないためです
> （`config.toml` はリポジトリ内のものが効くので、配色の設定はそちらに入っています）。
> 空のままでよく、Streamlitへ何も送信されません。

画面の配色は `.streamlit/config.toml`、細かい見た目は `ui_style.css` にあります。

### 通しの流れを試す（フォルダ監視での自動取り込み）

`manager/watch_inbox.py` は、監視フォルダ（デフォルトは `incoming/`）に置かれた画像を自動で
検出し、パイプラインによる読み取りとDB保存まで一気に行うスクリプトです。
撮影→送出→取り込み→読み取り→保存→一覧の通しの流れにおける、PC側の取り込み口にあたります。

```powershell
venv\Scripts\python.exe manager\watch_inbox.py
```

| オプション | 意味 | デフォルト値 |
|---|---|---|
| `--watch-dir` | 監視対象フォルダ | リポジトリ直下の `incoming/` |
| `--db` | 取り込み結果を保存するSQLite DBのパス | リポジトリ直下の `manager.db` |
| `--images-dir` | 原画像の恒久保存先 | リポジトリ直下の `images/` |
| `--use-vlm` | VLM（Ollama）を使う場合に指定（デフォルトは無効） | 無効 |
| `--no-save` | DBへ保存せず表示のみ行う（従来の動作） | — |

- 監視フォルダに画像（`.jpg`/`.jpeg`/`.png`）を置くと自動検出され、パイプラインで読み取りが
  実行されてDBへ保存されます。VLMも使う場合は起動時に`--use-vlm`を付けてください。
- 画像と**同じ名前のサイドカーJSON**（`example.jpg` なら `example.json`）を一緒に置くと、
  `local_id`/`captured_at`/`device_name`/`operator_value`/`operator_note` の各フィールドが
  メタデータとして保存されます。どの項目も省略可能で、サイドカーJSONが無くても
  画像だけで取り込めます（その場合の機器名は`unknown`になります）。
- 保存された原画像は `images/` フォルダに**SHA-256内容ハッシュ名**（`<内容ハッシュ>.jpg`等）で
  恒久保存されます。**同一内容（同一ハッシュ）の画像は重複排除され、2回目以降は取り込まれません**
  （コンソールに「重複画像のためスキップしました」と表示されます）。
- 起動時に監視フォルダ内に既にある画像も、まとめて取り込みます。
- 取り込んだ結果は `app.py`（Web UI）の「記録」タブから一覧を確認できます
  （両方ともデフォルトで同じ `manager.db` を読みます）。
- 停止は `Ctrl+C` です。

### 保存済み画像を別のパイプライン版で再処理する

`manager/reprocess.py` は、`images/` に保存済みの原画像を指定したパイプライン版で一括再処理し、
結果を新しいレコードとして追加するコマンドです。パイプラインを改良した前後で結果を比較したい
ときに使います。

```powershell
# リポジトリ直下で実行。--pipeline-version は必須
venv\Scripts\python.exe manager\reprocess.py --pipeline-version v1
```

| オプション | 意味 | デフォルト値 |
|---|---|---|
| `--images-dir` | 再処理する原画像フォルダ | リポジトリ直下の `images` |
| `--db` | 保存先SQLite DBのパス | リポジトリ直下の `manager.db` |
| `--pipeline-version` | 保存するパイプライン版（**必須**） | なし（指定必須） |
| `--use-vlm` | VLM（Ollama）を使用する（デフォルトは無効） | 無効 |

- `--images-dir` 内の `.jpg`/`.jpeg`/`.png` を1枚ずつ再処理します。
- **既存レコードは上書きしません。** 再処理の結果は新しいレコードとして追記され、
  `pipeline_version` 列に指定した版が記録されます。同じ画像に対する複数版の結果が
  履歴として並ぶことになります。
- 終了時に成功した件数と、再処理に失敗した画像のパスが表示されます。

---

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
