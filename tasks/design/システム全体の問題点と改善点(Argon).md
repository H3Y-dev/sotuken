スマホ撮影からPC受信・USB吸い出し・フォルダ監視・読み取り・DB保存・Streamlit表示・CSV出力までの全経路を精査した。
最優先の課題は、`storage.py` に追加済みの機器ID・撮影日時等の新6列が `save_reading` や `ingest.py` に未接続で「DBの件」が途中で止まっている点にある。
次に、受信口とUSB吸い出しの競合や同名スキップによるサイドカーJSON消失、および `run_pc.py` が監視プロセスを起動しない点が「実機の通し」を阻害している。
読み取り精度では、`scale_value_detect.py` が2条件一致だけで `is_confident=True` に上書きする不具合により、誤読が「要確認」にならず「正常」として通過する。
11/5に向けては、W-B残タスク（B4〜B8）の結線、監視の一体起動、誤読の要確認化、OCR重複排除の順に手を打つのが最も効果が高い。

---

## 1. データを失う・整合性が失われる危険

### 1-1. 【高】W-B（機器ID・時刻列）の途中段階による保存経路の断絶
- **何が問題か**: `manager/storage.py:89-107` で `meter_readings` に `device_id`, `device_id_source`, `device_id_issue`, `captured_at`, `received_at`, `image_rel` の6列が追加され、`devices` 表（177-188行目）と `manager/devices.py`、`manager/qr_decode.py` も実装済みである。しかし `manager/storage.py:30-52`（`MeterReading`）、`252-268`（`save_reading` の `INSERT`）、`318-354`（`get_all_readings` の `SELECT`）にこれら6列が含まれていない。また `manager/sidecar.py:8-20` に `device_id` が無く、`manager/ingest.py:63-135` も `qr_decode` や `devices.register_device` を呼んでいない。
- **なぜ問題か**: 現状のまま実機の通しを動かしても、機器ID・出所・撮影日時・取込日時・相対パスがDBに一切保存されず全行 `NULL` になり、11/5の基準である「DBの件」を満たせない。
- **直す案**: `tasks/design/機器ID設計.md` 9章のB4（`sidecar.py`）・B5（`ingest.py` と `storage.py` の読み書き拡張）を最優先で実装し、既存のB1〜B3と結線する。

### 1-2. 【高】同名画像の重複スキップ時に後着サイドカーJSONを破棄・端末削除する問題
- **何が問題か**: `manager/receiver.py:298-303` は `final_image_path` が既に存在すると `final_json_path` を書かずに `200 duplicate` を返す。`manager/usb_pull.py:200-204` も画像が `incoming/` に存在すると、`final_json_path` の有無や中身を確かめずにスマホ側のJSONと画像を両方 `adb shell rm` で削除する。
- **なぜ問題か**: 画像だけが先に届いた後でサイドカーJSON（機器名・真値）が再送・吸い出しされた場合、JSONが保存されないままスマホ側からも消去され、メタデータが永久に失われる。
- **直す案**: 画像が既存でも `final_json_path` が存在しないか内容が異なる場合は `.part` 経由でJSONを保存し、`manager/watcher.py:121-137`（`_refresh_sidecar`）でDBへ反映させてから端末側ファイルを削除する。

### 1-3. 【高】Wi-Fi追い送りとUSB吸い出しの同一ファイル名に対する並行書き込み競合
- **何が問題か**: スマホの `SendRouter.kt:83-107` は、オフライン時に `outbox` へ書き出した項目をWi-Fi回復時に同じベース名（`YYYYMMDDTHHMMSS_<localId>`）でHTTP再送する。このときUSBが繋がっていると、`manager/receiver.py:308-319` と `manager/usb_pull.py:206-298` が同じ `incoming/` 内で同時に書き込みとリネームを行う。さらに画像取得失敗時に `usb_pull.py:260-270` の `rollback()` が `final_json_path` を削除するため、`receiver.py` が直前に保存した正式なJSONまで消してしまう。
- **なぜ問題か**: 無線とUSBの境界でWindowsのファイルロックエラー（`PermissionError`）やサイドカーJSONの消失が起き、機器名なし（`unknown`）の記録が作られる。
- **直す案**: 一時ファイル名にプロセスIDと乱数を含め（`<name>.<pid>.<rand>.part`）、`usb_pull.py` では開始時とリネーム直前に `final_image_path` の存在を再確認し、他プロセスが作った `final_json_path` をロールバックで消さないようにする。

### 1-4. 【高】再処理（`reprocess.py`）と手動読み取り（`app.py`）による重複行の増殖
- **何が問題か**: `manager/reprocess.py:42-47` は再処理時に既存行の機器名を引き継がず、常に `device_name="unknown"` で新しい行を追加する。また `app.py:189-197`（`manager/manager.py:44-83`）の手動読み取りは `get_processed_hashes()` を検査しない。一方、`manager/export.py:101-126`（`latest_per_device`）は同一 `image_sha256` の重複排除（最大 `id` 採用）を行わず、`unknown` の行を機器ごとに束ねず全件リストに追加する（118行目）。
- **なぜ問題か**: `reprocess.py` を1回実行するだけで、全画像分の「名前なし（要確認）」行が最新値一覧と点検結果CSVに並び、正しい機器名の記録が埋もれる。
- **直す案**: `機器ID設計.md` のB6・B8に従い、`reprocess.py` で同一 `image_sha256` の既存行から機器ID・機器名・時刻を引き継ぎ、`export.py` では同一 `image_sha256` につき最大 `id` の1件だけを採用する。

### 1-5. 【中】SQLiteの同時接続設定（WAL・timeout）不足と例外時の接続リーク
- **何が問題か**: `manager/storage.py:71-74` の `sqlite3.connect(self.db_path)` は `timeout` 未指定（既定5秒）かつジャーナルモードが既定の `DELETE` になっている。また `save_reading`（250-273行目）や `update_reading_metadata`（275-285行目）は `with self.connection():` を使わず、`conn.commit()` 前に例外が出ると `conn.close()` が呼ばれない。
- **なぜ問題か**: `watch_inbox.py` の連続書き込みと `app.py` の読み書きが重なった際や、例外発生後に `database is locked` が起きやすい。
- **直す案**: 接続時に `timeout=15.0` と `PRAGMA journal_mode=WAL;` を設定し、`Storage` の全メソッドで `with closing(self._get_connection()) as conn, conn:` を徹底する。

### 1-6. 【中】`app.py` の手動アップロード一時ファイル（`temp_<ファイル名>`）の衝突と残存
- **何が問題か**: `app.py:177-179, 224-225` は画像選択時にカレントディレクトリへ `temp_ + uploaded_file.name` を書き込み、「読み取る」が成功したときだけ削除する。
- **なぜ問題か**: ボタンを押さずに閉じた場合や例外時に一時ファイルが残り、複数タブで同名ファイルを選ぶと中身が上書きされる。
- **直す案**: `tempfile.NamedTemporaryFile(delete=False, suffix=ext)` を使い、`try ... finally` で確実に削除する。

---

## 2. セキュリティ

### 2-1. 【高】`export_to_csv` におけるCSV数式インジェクション対策の漏れ
- **何が問題か**: `manager/export.py:164-166` の `export_inspection_csv` には先頭 `=`, `+`, `-`, `@` に `'` を付ける `safe_cell` があるが、同ファイルの `export_to_csv`（48-64行目）には適用されていない。また `safe_cell` 自体も先頭の空白やタブ・改行（`\t`, `\r`, `\n`）に続く `=` 等を検査していない。
- **なぜ問題か**: 機器名や備考に数式文字列が入った場合、`readings_export.csv` をExcelで開いた際に数式が実行される危険がある。
- **直す案**: `safe_cell` をモジュール先頭へ出して `\t`, `\r`, `\n` および `lstrip()` 後の `=`, `+`, `-`, `@` を無害化し、`export_to_csv` と `export_inspection_csv` の全文字列列に適用する。

### 2-2. 【中】受信口（`0.0.0.0:8765`）の平文HTTP通信と合言葉の平文保存・画面常時露出
- **何が問題か**: `manager/receiver.py:441-445` は `0.0.0.0:8765` で平文HTTPを待ち受け、プライベートIPv4からの全接続を受け付ける（85-98行目）。合言葉は `manager/pc_config.json` に平文保存され（79-80行目）、`app.py:126, 130` のサイドバーと `run_pc.py:25` のコンソールに常時平文で表示される。スマホ側も `ReceiverSettings.kt:31-35` で通常の `SharedPreferences` に保存し、`network_security_config.xml:3` で全通信の平文HTTPを許可している。
- **なぜ問題か**: 大学や工場の共有Wi-Fi上での盗聴や、PC画面の覗き見・画面共有から合言葉が漏れると、同一LAN内の第三者が任意の画像を送り込める。
- **直す案**: `app.py` の合言葉は初期状態で伏せ字（または折りたたみ）にし、`pc_config.json` は `%LOCALAPPDATA%` 配下に置いてユーザー本人のみ読み書き可（Windows ACL）にする。

### 2-3. 【中】受信口のスレッド無制限生成とソケットタイムアウト未設定によるDoSの危険
- **何が問題か**: `manager/receiver.py:335` の `ReceiverServer` は `ThreadingHTTPServer` をそのまま使い、`ReceiverHandler` に `timeout` が設定されていない。`do_POST`（283行目）は `self.rfile.read(content_length)` で最大30MBをブロッキング読み込みする。
- **なぜ問題か**: 送信途中で電波が途切れた接続や低速接続が重なると、スレッドとメモリ（1接続最大30MB）が解放されず、`app.py` プロセス全体が応答不能になる。
- **直す案**: `ReceiverHandler.timeout = 15` を設定し、同時処理スレッド数をセマフォ等で上限（例: 8接続）に抑える。

### 2-4. 【低】ファイル名のパス結合・Streamlit待受アドレス・固定依存の脆弱性
- **何が問題か**: `app.py:177` は `uploaded_file.name` に `os.path.basename` を通さず連結している。また `.streamlit/config.toml` に `server.address` の指定がなく、StreamlitがLAN側からも開ける状態になり得る（推測: ファイアウォール設定による）。さらに `requirements.txt:10-38` で2023〜2024年頃の版（`pillow==10.4.0`, `pyarrow==17.0.0`, `streamlit==1.40.1` 等）に固定されており、既知の脆弱性が含まれる可能性がある（推測）。
- **なぜ問題か**: Streamlit画面がLANに露出していると、合言葉なしで全履歴の閲覧や画像アップロードが可能になる。
- **直す案**: `.streamlit/config.toml` に `[server]\naddress = "127.0.0.1"` を明記して外部公開を閉じ、`app.py:177` で `os.path.basename` を使う。

---

## 3. 精度と正しさ

### 3-1. 【高】誤読した値を「正常（`status="ok"`）」として通過させる判定の抜け穴
- **何が問題か**: `manager/record.py:5-11` の `judge_status` は `scale_confident is False` のときだけ `"low_confidence"`（要確認）にするが、上流に以下の4つの抜け穴がある。
  1. **2条件一致による信頼度の強制上書き**: `scale_value_detect.py:1151-1152` は、前処理4試行のうち2試行で `min_value`/`max_value` が一致しただけで、各試行が `determine_min_max`（855-868行目）で判定した `is_confident=False`（対応点数6未満やフルスケールが標準数外）を **`agreed['is_confident'] = True` に無条件で上書き**している。
  2. **OCRとVLMの不一致放置**: `scale_value_detect.py:1225-1226` でOCRとVLMの範囲が `disagree` かつ盤面位置の裏取りに失敗しても、`is_confident = True` のまま返している。
  3. **針が範囲外を指して端へ丸められた場合**: `meter_reader.py:65-85` の `_clamped` は、ゼロ点誤検出や針誤検出で針がスケールの外（死角）を指していても、警告フラグなしで `0.0` または `1.0` に丸める。
  4. **針の信頼度の未使用**: `meter_reader.py:378-382` で計算した `needle_confidence` を、`meter_pipeline.py:204-217`（既定経路）が捨てており、`judge_status` も参照しない。
- **なぜ問題か**: たとえば3点しか数字が対応付かずフルスケールが異常値（`501` 等）でも、2つの前処理で同じ誤読になれば「✓ 正常」として点検CSVに出力され、人が見落とす。
- **直す案**: `scale_value_detect.py:1152` で元の試行の `is_confident` と `is_plausible_fullscale` を維持し、OCR/VLM不一致時・針の範囲外クランプ発生時・針候補が競合している時はすべて `"low_confidence"`（要確認）にする。

### 3-2. 【高】OCRが数字の後ろに「1」を足す誤読と、マイナス記号を落とす問題
- **何が問題か**:
  1. `scale_value_detect.py:43-51, 147-159`: RapidOCRが数字ラベルと隣の目盛り線を1つの枠で囲み、目盛り線を `1`, `l`, `I`, `|` と読むと、`_CONFUSION_MAP`（45行目）がすべて `'1'` に変換するため、`10`→`101`、`50`→`501` のように末尾に `1` が付く。`_split_merged_number_boxes`（58-133行目）は偶数桁の2ラベル融合しか扱わないため、この誤読を直せない。
  2. 連成計などのマイナス記号は小さく細いためOCRで落ちやすく、`-0.1` が `0.1` と読まれる。すると `determine_min_max`（846行目）で単調列から外れるか正の最小値になり、さらに883行目の `all_observed_non_negative` が負方向への目盛り補完を止めている。
- **なぜ問題か**: フルスケールや最小値が大きく狂い、合成20枚中16枚失敗・実機16件中3件範囲不明の直接原因になっている。
- **直す案**:
  1. 他の数字群から推定した刻み幅（`step`）に乗らない候補のうち、2文字以上で末尾が `'1'` のものは `text[:-1]` が等差格子に乗るかを検査し、乗れば末尾の `'1'` を目盛り線の誤連結として除去する。
  2. `0` の目盛りより手前（反時計回り側）に主目盛りと正の数字（例: `0.1`）が並び、`0` の先にも `0.1, 0.2` が並ぶ場合は、`0` より手前の数字にマイナス符号を補った候補列も評価し、883行目の非負制限を緩和する。

### 3-3. 【高】実機通し経路（`watch_inbox.py`・`app.py`）でVLMが既定で無効になっている問題
- **何が問題か**: `evaluate.py:196` では `use_vlm=True` が既定だが、`manager/pipeline_caller.py:9`、`app.py:19`、`manager/watch_inbox.py:50-54`、`manager/reprocess.py:24` はすべて `use_vlm=False` が既定になっている。さらに `devices` 表（またはQRの `min`/`max`）の目盛範囲を読み取り時に参照する経路も無い。
- **なぜ問題か**: 現場やデモでオプションを付けずに起動するとVLM補助が一切動かず、OCR単独で3点以上対応付かない画像がすべて範囲不明（`scale_range_unresolved`）で失敗する。
- **直す案**: 起動時に `vlm_scale_value.check_availability()` と推論速度を1回確認し、利用可能なら `watch_inbox.py` と `app.py` でもVLMを有効化する。加えて、QRや `devices` 表で既知の機器は、目盛範囲の検証・フォールバックにその `min_value`/`max_value` を使えるようにする。

---

## 4. 性能と容量

### 4-1. 【高】1枚あたり最大11回以上のOCRと最大3回のVLMが直列実行される処理構造（1枚約22秒の原因）
- **何が問題か**: 1枚の画像を読む中で以下の重複・直列処理が行われている。
  1. `meter_pipeline.py:118`: OCRを試す前に、毎回 `vlm_scale_value.detect_meter_bbox`（VLM 1回目）を呼ぶ。
  2. `orientation.py:20-23`: 0度で十分に数字が読めていても、90/180/270度を含む4方向すべてで `read_scale_numbers`（OCR 1〜4回目）を実行し、読んだ数字の結果も捨てている。
  3. `scale_value_detect.py:1111-1130`: `input_ticks`, `original`, `clahe1.5`, `clahe2.5` の4回と1130行目の1回で計5回OCRを実行しており、そのうち **`input_ticks`・`original`・1130行目の3回は全く同じ元画像 `img` に対して重複してRapidOCRを実行**している。
  4. `scale_value_detect.py:1134`: OCRの4試行が完全に一致して高信頼であっても、毎回 `vlm_scale_value.read_min_max`（VLM 2回目）を呼ぶ。
  5. `manager/overlay.py:41`: オーバーレイ描画時に `meter_reader.detect_needle` を再計算している。
- **なぜ問題か**: 同じ画像への3重OCR、不要な回転OCR、高信頼時にも走るVLMが重なり、1枚約22秒（CPU環境では数分）かかっている。`watcher.py` は1枚ずつ直列処理するため複数枚の連続撮影で大きく遅延する。
- **直す案**:
  1. `scale_value_detect.py:1111-1130` で元画像 `img` のOCR結果を1回だけ計算して3箇所で共有する（OCR 2回削減）。
  2. `orientation.py:20` で0度の検出数が十分（例: 5個以上）なら他3方向のOCRを省略し、0度のOCR結果を後段へ渡す（OCR 3〜4回削減）。
  3. `detect_meter_bbox` と `read_min_max` は、OpenCV検出やOCRクロスチェックが失敗・低信頼のときだけ呼ぶ遅延評価にする（通常画像のVLMを0回に削減）。

### 4-2. 【中】`incoming/`・`images/`・`overlays/` の無制限蓄積と起動時ハッシュ再計算
- **何が問題か**: 旧 `logs/` の肥大化（6.2GB）は `ingest.py:97, 107` と `storage.py:14` で解消済みだが、現在も1撮影につき `incoming/`・`images/`・`overlays/`・`.cache/thumbs/` およびスマホの `captures/`・`outbox/` に画像が残り続ける。さらに `watch_inbox.py:78-80, 130` は起動のたびに `incoming/` 全画像のSHA-256を計算し直す。
- **なぜ問題か**: 運用を続けるとディスク容量を圧迫し、`incoming/` の枚数が増えるほど `watch_inbox.py` の起動と毎回の `get_processed_hashes()` 照合が遅くなる。
- **直す案**: 取り込み完了かつサイドカー反映済みの `incoming/` ファイルを一定期間後に削除（または整理コマンドで削除）できるようにし、`watch_inbox.py:78` の `processed_hashes` はメモリ上のセットを更新して毎回DB全件クエリしないようにする。

---

## 5. 運用・使いやすさ

### 5-1. 【高】3プロセスの個別起動が必要で、`watch_inbox.py` 忘れに気づけない問題
- **何が問題か**: `run_pc.py:17-32` は `receiver.py` と `app.py` しか起動せず、`watch_inbox.py` と `usb_pull.py` は別ターミナルで手動起動する設計になっている（`SETUP.md:391-407`）。一方、スマホは `receiver.py` が200を返せば「送信済み」と表示する（`SendRouter.kt:61-63`）。
- **なぜ問題か**: 現場で `run_pc.py` だけ起動して `watch_inbox.py` を忘れると、スマホでは「送信済み」になるのにPCの「記録」タブには何も出ず、画面に「監視が停止している」という警告も出ないため原因が分からない。
- **直す案**: `run_pc.py`（または `app.py` の `@st.cache_resource`）から `FolderWatcher`（取り込み監視）もバックグラウンドスレッドで自動起動するか、`app.py` に監視稼働状態と `incoming/` の未処理件数を表示する。

### 5-2. 【中】画面（`app.py`）に未処理件数・失敗理由・現場入力値が出ず、自動更新もされない問題
- **何が問題か**:
  1. `app.py:139-143`: バックグラウンドでDBに記録が増えても、ブラウザを手動リロードするか画面部品を触るまで表が更新されず、解析中かどうかも分からない。
  2. `app.py:31-40, 251-261`: 最新値一覧にも全履歴にも `failure_code` / `failure_detail`（どこで落ちたか）や `operator_value`（現場入力値）の列が無い。
  3. `app.py:295-315`: 「CSVを書き出す」「JSONLを書き出す」は画面の期間・機器フィルタを無視して全履歴を書き出し、毎回 `readings_export.csv` を上書きする。
- **なぜ問題か**: 点検者がPC画面を見ても「なぜ失敗・要確認なのか」「あと何枚処理待ちなのか」が分からず、撮り直しや現場入力値での確認ができない。
- **直す案**: 記録タブに「最新の状態に更新」ボタンと `incoming/` 待ち件数を置き、表に「要確認・失敗の理由」「現場入力値」列を追加する。

### 5-3. 【中】スマホの設定手入力の負担と、送信失敗（`FAILED`）からの再送手段の欠如
- **何が問題か**:
  1. `MeterCaptureApp.kt:160-227`: 送信先URLと32文字の合言葉を手打ちする必要があり、保存時に `/health` の疎通確認を行わない。
  2. `QueueListScreen.kt:64-167`: 履歴画面に再試行ボタンが無く、容量不足等で `SendState.FAILED` になった項目を `QueueStore.retry()`（`QueueStore.kt:83-90`）で再送するUI経路が無い。
- **なぜ問題か**: 現場で32文字のトークンを手入力すると打ち間違いが起きやすく、また一度 `FAILED` になった写真がスマホ内に取り残される。
- **直す案**: PCのサイドバー（`app.py:120-130`）に送信先URL＋合言葉のQRコードを表示してスマホで読み取れるようにし、スマホの設定保存時テスト接続と履歴画面の「再送」ボタンを追加する。

---

## 6. テストと保守

### 6-1. 【中】コードの重複・インポート方式の不統一・相対パスの散在
- **何が問題か**:
  1. `get_default_incoming_dir()` が `manager/receiver.py:44-47` と `manager/usb_pull.py:22-25` に重複し、`manager/watch_inbox.py:27` にも同じ式が直書きされている。
  2. `manager/manager.py:12-16` だけが `sys.path.insert` で `from record import ...` と書いており、他ファイルの `from manager.record import ...` と混在している。
  3. `app.py:139, 177, 195-196, 296, 307`、`image_cache.py:7`、`manager/overlay.py:66`（`os.path.relpath`）、`manager/ingest.py:68-69`、`manager/reprocess.py:52, 76-77` がカレントディレクトリ基準の相対パスを使っている。
- **なぜ問題か**: 起動ディレクトリが変わると別々のDBやフォルダを参照し、`manager.py` の二重インポートでクラス型が不一致になるリスクがある。
- **直す案**: `manager/paths.py` に全パス解決を集約し、`manager/manager.py` のインポートを `from manager.record import ...` に統一する。

### 6-2. 【中】設計書・ドキュメント・実装の食い違い（特に撮影時刻と点検CSV列）
- **何が問題か**:
  1. `manager/export.py:57, 75` は、`MeterReading` に `captured_at` が無いため、DB保存時刻である `timestamp` を `captured_at`（撮影日時）という列名に読み替えてCSV/JSONLへ出力している。
  2. `tasks/design/機器ID設計.md:70-76, 189`（点検ID列・単位列あり、manifest方式）と `tasks/design/PCインストーラー化.md:20`（改訂節: 初版は単位・点検IDを出さない）と現行 `manager/export.py:174`（5列のみ）で点検CSVの列定義が食い違っている。
  3. `SETUP.md:190` はサイドカー項目に `device_id` をまだ記載していない。
- **なぜ問題か**: オフライン撮影後にUSBでまとめて吸い出すと、CSVの `captured_at` がすべてPC取り込み時刻になり、実際の撮影時刻と食い違う。
- **直す案**: B4〜B6で本物の `captured_at` をDBへ保存して `export.py` の `timestamp` 別名を廃止し、点検CSVの列定義を `機器ID設計.md` に統一する。

### 6-3. 【低】画面（`app.py`）とプロセス間競合の自動テスト不足
- **何が問題か**: `tests/` に50本のテストがあるが、`app.py` のUIテスト（`streamlit.testing.v1.AppTest`）と、`receiver.py`・`usb_pull.py`・`watch_inbox.py` を同時に動かす競合結合テスト、およびAndroidの `QueueSendWorker`・`QueueListScreen` のテストが無い。
- **なぜ問題か**: 画面表示の崩れやマルチプロセス実行時のロック・競合が手動確認まで検出できない。
- **直す案**: `AppTest` による `app.py` のスモークテストと、受信→監視→DB保存→CSV出力の通し結合テストを追加する。

---

## 7. インストーラー化に向けた障害

### 7-1. 【高】作業フォルダ直下への書き込み前提と、Streamlit初回メール入力待ちによる停止
- **何が問題か**: 6-1で挙げた相対パス群に加え、`manager/receiver.py:40-41` はコードと同じ `manager/pc_config.json` に書き込み、`manager/overlay.py:66` は作業フォルダからの `os.path.relpath` をDBに保存する。さらに `run_pc.py:31` は `["streamlit", "run", app_path]` だけを渡しており、`~/.streamlit/credentials.toml` が無いクリーンなPCでは初回の `Email:` 入力待ちで起動が止まる（`SETUP.md:151-165`）。
- **なぜ問題か**: インストーラー配置後の環境で権限エラーや画像リンク切れが起き、また初回起動時にコンソールで止まってブラウザが開かない。
- **直す案**: `manager/paths.py` でデータを `%LOCALAPPDATA%\SotukenMeter\` 配下へ集約し、DBにはデータフォルダ基準の相対パス（`image_rel`）を保存する。`run_pc.py:31` には `--server.headless=true` と `--browser.gatherUsageStats=false` を付け、起動後に `webbrowser.open` でブラウザを開く。

### 7-2. 【中】子プロセス管理の不在と、Ollama接続先固定・CPU環境での推論遅延
- **何が問題か**: `run_pc.py` に監視・USB・専用Ollamaを起動・終了管理する仕組みがない。また `vlm_scale_value.py:57, 79, 148, 210` は `ollama.chat` を直接呼んでおり、ホスト（`127.0.0.1:11434`）やタイムアウトを指定できない。
- **なぜ問題か**: 配布先PCの既存Ollamaと競合するほか、GPU無しのPCでVLMが呼ばれると1枚数分かかり固まったように見える。
- **直す案**: `vlm_scale_value.py` で `ollama.Client(host=..., timeout=...)` を使うようにし、起動時の試行推論が遅い環境では自動で `use_vlm=False`（OCRのみ）へ切り替える。

### 7-3. 【低】オープンソースライセンス表記（NOTICE）の未作成と `adb`・フォント依存
- **何が問題か**: 同梱予定のPythonパッケージ・RapidOCR・OpenCV・Ollama・Qwen3-VLのライセンス一覧（`THIRD_PARTY_NOTICES.txt`）が未作成である。また `manager/qr_label.py:205-209` はWindows標準の3フォント名のみを探す。
- **なぜ問題か**: インストーラー配布時にライセンスの帰属表示条件を満たせない。
- **直す案**: 配布前に `THIRD_PARTY_NOTICES.txt` を作成し、`adb` は任意機能として未検出時に画面上で導入手順を案内する。

---

## 8. 優先順位の提案（11/5の「DBの件」「通しを実機で動かす」に向けた上位10件）

| 順位 | 対象（重大度・節） | やること（対象ファイル） | 効果 | 手間 | リスク |
|---|---|---|---|---|---|
| 1 | W-B残タスクB4・B5の結線（高・1-1） | `sidecar.py` に `device_id` とUTC時刻正規化を追加し、`ingest.py` と `storage.py`（`save_reading`/`get_all_readings`/`MeterReading`）で新6列・PC側QR読み取り・`devices` 登録を繋ぐ | **極大**（「DBの件」の中核が開通） | 中（半日） | 低（既存テスト＋結合テストで検証可） |
| 2 | 再処理と出力の機器ID対応・重複排除 B6・B8（高・1-4, 6-2） | `reprocess.py` で既存行の機器情報を引き継ぎ、`export.py` で同一 `image_sha256` の最大 `id` 採用・本物の `captured_at` 出力・manifest保存を実装する | **極大**（「DBの件」の完了、名前なし増殖の防止） | 中（半日） | 低（出力列のテスト更新が必要） |
| 3 | `run_pc.py` での監視一体起動とヘッドレス設定（高・5-1, 7-1） | `run_pc.py`（または `app.py`）で `watch_inbox` 相当の `FolderWatcher` も起動し、Streamlitに `--server.headless=true` と `127.0.0.1` 指定を渡す | **大**（「実機の通し」で起動忘れ・初回停止がなくなる） | 小（2時間） | 低（二重起動防止ロックを入れる） |
| 4 | 誤読の「要確認」判定強化（高・3-1） | `scale_value_detect.py:1152` の `is_confident=True` 強制上書きを止め、標準数外・OCR/VLM不一致・針の範囲外クランプを `judge_status` で `low_confidence` にする | **大**（誤読を「正常」として出す危険を遮断） | 小（2時間） | 低（読み取り値自体は変えず状態表示のみ改善） |
| 5 | 同名画像スキップ時の後着JSON保存と競合防止（高・1-2, 1-3） | `receiver.py:298` と `usb_pull.py:200` で画像既存時も未保存・更新JSONを反映し、一時ファイル名にPID/乱数を入れてロールバック競合を防ぐ | **大**（無線追い送りとUSB併用時のデータ消失防止） | 小（2〜3時間） | 低（単体テストで再現・検証しやすい） |
| 6 | OCR重複実行の削減とVLM遅延呼び出し（高・4-1, 3-3） | `scale_value_detect.py:1111-1130` の同一画像3重OCRを1回に共有し、`orientation.py` は0度で十分なら他方向を省略、VLMはOCR低信頼・失敗時のみ呼ぶ | **大**（1枚22秒の読み取り時間を大幅に短縮） | 中（3〜4時間） | 中（`evaluate.py` で精度が落ちないか確認が必要） |
| 7 | OCRの「末尾1付加」補正と負数目盛り対応（高・3-2） | 等差格子から外れる末尾 `'1'` 候補の `'1'` 除去検査と、`0` より手前の目盛りに対する負数候補の評価を `scale_value_detect.py` に追加する | **大**（実機・合成画像の範囲不明と大誤差を削減） | 中（半日） | 中（既存の正数メーターで副作用がないか回帰確認） |
| 8 | SQLiteのWAL有効化・timeout設定・接続管理統一（中・1-5） | `storage.py:71` で `timeout=15.0` と `PRAGMA journal_mode=WAL` を設定し、`save_reading` 等を `with self.connection():` に統一する | **中**（実機通し中の `database is locked` を防止） | 小（1時間） | 低（SQLite標準機能で副作用が小さい） |
| 9 | 記録タブ（`app.py`）の更新ボタン・未処理件数・失敗理由表示（中・5-2） | `app.py` に更新ボタン、`incoming/` 待ち件数、失敗・要確認理由列、現場入力値列を追加し、手動アップロードの一時ファイルを安全に消す | **中**（実機デモ・現場確認での分かりやすさ向上） | 小（2〜3時間） | 低（UI表示のみの変更） |
| 10 | CSV数式インジェクション対策の共通化とスマホQR設定（高/中・2-1, 5-3） | `export.py` の `safe_cell` を `export_to_csv` にも適用し、`app.py` サイドバーの送信先設定をQRコード表示・スマホ側再送ボタン追加へ繋げる | **中**（出力の安全性確保と実機接続の手間削減） | 小〜中（2〜4時間） | 低（既存の `qrcode` ライブラリをそのまま利用可） |
