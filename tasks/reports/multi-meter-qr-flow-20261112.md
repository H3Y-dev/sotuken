# 複数機器QR点検フロー試験（2026-11-12）

## 結果

HTTP受信から実OCR、SQLite、既存の集計関数まで実行した。6枚すべてが点検 `I-MULTI-20261112`、ルート `R-MULTI` に紐づいた。撮り忘れとルート外は区別できた。ただし、一覧選択の出所 `list` に2つの不一致があり、指定どおりのmanifestでは完了できない。本番コードは変更していない。

## 実行条件と再現

- 作業ブランチ: `test/multi-meter-qr-flow`。指定worktreeのみ変更。push・マージなし。
- Python: `C:\卒研\git_stk\sotuken\venv\Scripts\python.exe`。
- 実行: `python tools/multi_meter_flow.py`。受信口は127.0.0.1のOS割当空きポート。一時フォルダにDB・incoming・保存画像・overlayを作り、終了時に削除する。
- 既存の `manager/receiver.py`、`execute_pipeline(use_vlm=False)`、`ingest_result` を実行する。watcherの非同期監視は使わず、受信済みファイルを順に取り込む。Ollamaは使わずRapidOCRで読む。
- 実データのDB・images・incomingは使用していない。合成画像セットの正解JSONから、正面画像で異なる機器IDを6台選んだ。元画像や元サイドカーは変更していない。
- 原始結果は `multi-meter-flow-result.json`。全DB列、送信名・元画像絶対パス・SHA256・manifest拒否応答・画像QRのデコード結果・集計結果・Ollamaの実行記録を保存している。一時DBそのものは残していない。

## 写真と期待値

ルート順はSYN-001、SYN-003、SYN-002、SYN-004、SYN-006。SYN-006は送信しない。SYN-005はルート外として追加した。

送信名は `20261112T09000N_N.png`（N=1〜6）。元画像はすべて `C:\卒研\合成画像\テスト用QR付き_20261030\画像\正面\` 配下。

|N|元画像|期待する機器ID|スマホの出所|正解値|
|---|---|---|---|---:|
|1|p150_v07_var1_正面.png|SYN-001|qr|10.5|
|2|p150_v14_var1_正面.png|SYN-003|qr|21.0|
|3|p150_v23_var1_正面.png|SYN-002|qr|34.5|
|4|p16_v36_var1_正面.png|SYN-004|list|5.76|
|5|p16_v48_var1_正面.png|SYN-005|qr|7.68|
|6|p16_v48_var1_正面.png|SYN-005|機器ID・出所なし（PC画像QR用の追加試験）|7.68|

指定の5枚に加え、PCによる画像QRの補完を通すため6枚目を追加した。6枚目は同じPNGの末尾に識別バイトを付け、重複ハッシュによる省略を避けた。画素は同じで、実画像デコードとQR読み取りが成功した。スマホで撮り直した写真の再現ではない。

## DB結果

全行のinspection_idは `I-MULTI-20261112`、route_idは `R-MULTI`。DBのidとNは一致する。

|DB id|device_id|DBの出所|期待との照合|読み取り値|stage|status|
|---:|---|---|---|---:|---|---|
|1|SYN-001|sidecar_qr|一致（スマホQR）|10.778675|ok|low_confidence|
|2|SYN-003|sidecar_qr|一致（スマホQR）|21.622575|ok|low_confidence|
|3|SYN-002|sidecar_qr|一致（スマホQR）|36.750197|ok|low_confidence|
|4|SYN-004|sidecar|不一致（一覧という出所が消える）|5.713452|ok|low_confidence|
|5|SYN-005|sidecar_qr|一致（ルート外・スマホQR）|7.903011|ok|low_confidence|
|6|SYN-005|pc_qr|一致（PCの画像QR）|7.903011|ok|low_confidence|

読み取り値は正解値と完全一致しない。許容誤差の指定がないため、精度の合否は判定していない。全件low_confidenceなので、人による確認が必要な結果として扱う。`manager/record.py:judge_status` はscale_confidentがFalseの場合にこの状態を返す。今回のraw_dataも全件scale_confident=falseだった。stage=okだけで精度の合格とは判断できない。

## 受信状態・進捗・機器一覧

|確認|期待|実測|
|---|---|---|
|manifest前|受信中|受信中、matched=0|
|listを含むmanifest|受理|不一致: HTTP 400|
|診断用manifest送信後・OCR前|全写真到着|完了、matched=6、missing_photos=[]|
|OCR後|全写真到着|完了、matched=6、missing_photos=[]|
|arrived_manifest_devices・OCR前|到着済み6枚分|6要素|
|arrived_manifest_devices・OCR後|DB行との二重計上なし|空配列|
|ルート内4台|撮影済み|4台すべて撮影済み|
|SYN-006|未撮影|未撮影、スマホ申告も未撮影|
|SYN-005|追加|追加、スマホ申告も追加|

400応答を記録後、診断継続のためmanifestの4枚目だけ `list` から既存の許容値 `sidecar` に置き換えて再送した。写真サイドカーの `list` は変更していない。「完了」はこの診断用manifestに対する結果であり、元のmanifestが受理されたことを意味しない。撮り忘れがあっても、manifestに挙げた写真が全部届けば受信状態は完了になる。

`inspection_devices` の実測:

|機器ID|写真枚数|情報の出所|
|---|---:|---|
|SYN-001|1|スマホ(QR)|
|SYN-002|1|スマホ(QR)|
|SYN-003|1|スマホ(QR)|
|SYN-004|1|なし（不一致: 一覧選択を期待）|
|SYN-005|2|PC(画像のQR)、スマホ(QR)|

撮影していないSYN-006は写真由来の機器一覧には現れず、route_progressには未撮影として現れる。

## 不一致と原因の推測

1. **manifestのlistが400になる。** `manager/routes.py:validate_manifest`（76行以降、出所の列挙チェック）にlistがない。実際の拒否と検証条件が一致する。
2. **一覧の出所を保存・表示できない。** `manager/sidecar.py:107-109` はqr/manual以外をNoneにする。`manager/ingest.py:_sidecar_identity`（36行以降）はその場合にsidecarを保存する。`manager/export.py:inspection_devices`（51行以降）の表示辞書にはlistもsidecarもなく、「なし」になる。受信段階で文字列listを送れても、一覧という意味がここで失われると考えられる。
3. **値の精度は未合格。** SYN-002の絶対誤差は約2.250197。他の誤差も原始結果から確認できる。QRのID対応は合っているため、機器取り違えによる誤差とは考えにくい。`manager/pipeline_caller.py:execute_pipeline` → `meter_pipeline.py:read_meter` 以下の読み取り処理の調査が別途必要。今回その内部原因までは特定していない。

## 取り込み時間・Ollama

時間はexecute_pipeline開始からingest_result完了まで。HTTP転送・事前のQRデコード確認は含まない。PC画像QR用の6枚目はingest_result内部のQRデコード時間を含む。最終実行（14:52開始）の秒数は次のとおり。

|写真N|取り込み秒数|
|---:|---:|
|1|13.064|
|2|16.299|
|3|22.483|
|4|14.419|
|5|20.510|
|6|17.447|

合計104.222秒、平均17.370秒/枚。初回も6枚すべて取り込めた。最終実行では実画像についても、1枚退避時に「不足あり」・matched=5を確認し、復帰後に全6枚を取り込んだ。

開始前・終了後の `ollama ps` はともに見出しのみ（実行中モデルなし）、終了時の `ollama stop qwen3-vl:4b-instruct` は終了コード0。VLMは無効にして実行した。

## 自動試験と残り

`python -m unittest tests.test_multi_meter_flow` は1件、失敗0・エラー0。OCRだけをモックし、ルート作成・HTTP取得・6枚送信・manifest拒否と診断用再送・DB取り込み・出所・点検ID・進捗・機器一覧を検証した。受信写真を1枚一時退避すると不足あり（matched=5、未着名1件）、戻すと到着済みとして扱われることも検証した。OCR前と後の進捗が同じになることも確認した。

`python -m unittest discover -s tests` は629件、失敗0・エラー0（初回128.652秒、最終再実行115.859秒・終了コード0）。新規試験の最終単独実行も1件、3.269秒、OK。故意に通信を中断する既存試験のConnectionAbortedErrorやStreamlitの実行コンテキスト警告は出るが、unittestの合否とは区別した。全試験ログは `multi-meter-unittest.log` に保存した。

実機で残る確認は、カメラからのQR読み取り、一覧選択の送信値、撮り忘れ・追加の完了確認、通信断と再送、manifest送信、USBテザリング、PC記録画面での表示。今回Android・エミュレータ・PCのGUIは操作していない。
