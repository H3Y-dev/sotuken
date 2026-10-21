# 通しの結線: 無線（Wi-Fi）を本線、USBでの自動吸い出しを予備にする 仕様

作成: 2026-10-21（Claude Opus。大久保の方針「サイトを動かしているPCに無線でつながったらそちらで自動送信。オフラインに備えてUSBでの自動吸い出しも作る」に基づく）
状態: 大久保のレビュー待ち。実装は段階ごとに委任し、Claudeが検証する。実機（SO-52E）での確認は大久保。

## 1. 目的

撮影 → 端末内キュー → **PCへ自動で届く** → 取り込み（`watch_inbox.py`）→ 読み取り → 一覧、を人手なしでつなぐ。
今は `QueueSendWorker` と `HttpSender` が `TODO()` のままで、キューに入った写真がPCへ届かない（`FolderSender` は単体テストだけ）。

## 2. 全体の形

```
[スマホ] 撮影 → キュー(PENDING) → 送信Worker
   ├─ PCの受信口に届く（Wi-Fi）     → HTTPで送る（本線）           → PCの incoming/ に置かれる
   └─ 届かない（工場内でオフライン等）→ アプリ専用の送信箱(outbox)に書く → USBで繋いだときPCが自動で吸い出す → incoming/
[PC] incoming/ → watch_inbox.py（既存・変更なし）→ 読み取り → SQLite → app.py の一覧
```

- PCの入口は今までどおり `incoming/` フォルダ1つ。無線もUSBも、最後は「サイドカーJSONを先、画像を後に、一時名で書いて正式名へリネーム」で置く（既存の取り込み規約。`watch_inbox.py` は変えない）。
- 送信箱はアプリ専用領域（`getExternalFilesDir(null)/outbox`）。ギャラリーに出ない・ほかのアプリから見えないので、「撮影画像を公開領域に常置しない」（`tasks/spec/2026-09-01_撮影から集約までの機能仕様.md`）を守れる。
- 同じ写真が両方の経路で届いても、PC側の重複排除（`image_sha256`）で1件になる。

## 3. PC側

### 3.1 受信口 `manager/receiver.py`（新規）

標準ライブラリだけで作る（`http.server.ThreadingHTTPServer`）。新しい依存を足さない。

| 項目 | 決め |
|---|---|
| 待ち受け | `0.0.0.0:8765`（ポートは設定で変更可） |
| 接続元の制限 | 接続元がプライベートIPv4（10/8、172.16/12、192.168/16）と127.0.0.1以外なら403 |
| 合言葉 | ヘッダー `X-Sotuken-Token` が設定値と一致しなければ401。設定値は初回起動時に乱数で作り `manager/pc_config.json` に保存（`.gitignore` に追加） |
| `GET /health` | 200 `{"ok": true, "service": "sotuken-receiver", "version": 1}` |
| `POST /upload` | 本文＝画像のバイト列。ヘッダー: `X-File-Name`（`YYYYMMDDTHHMMSS_<local_id>.<拡張子>`、英数と `_` `-` `.` のみ）、`X-Sidecar-Json`（サイドカーJSONをUTF-8→base64url）、`X-Image-Sha256`（本文のSHA-256、16進小文字）、`Content-Length` |
| 検査 | ファイル名の形、拡張子（jpg/jpeg/png）、大きさ上限30MB、SHA-256一致、サイドカーがJSONとして読め `local_id` がファイル名と一致 |
| 書き込み | `incoming/` へ、JSONを `.part` で書いてリネーム → 画像を `.part` で書いてリネーム |
| 応答 | 200 `{"stored": "<ファイル名>"}`。同じ名前が既にあれば200 `{"stored": ..., "duplicate": true}`（再送しても安全にする）。検査に落ちたら400と理由 |

起動のしかたは2つ:
- 単独: `venv\Scripts\python.exe -m manager.receiver`（`--port`、`--incoming`）
- **`app.py` を起動すると、受信口も一緒に動く**（`st.cache_resource` で1回だけ別スレッド起動。ポートが使用中なら起動せず画面に理由を出す）。ユーザーの方針「サイトを動かしているPCへ送る」に合わせる。

`app.py` のサイドバーに「スマホの送信先」として、PCのLAN内アドレス（`http://192.168.x.x:8765`）と合言葉を表示する。スマホ側はこれを一度入力するだけでよい。

### 3.2 USB自動吸い出し `manager/usb_pull.py`（新規）

- 5秒ごとに `adb devices` を見て、接続中の端末ごとに `/sdcard/Android/data/jp.sotuken.metercapture/files/outbox/` を一覧する。
- `<ベース名>.json` と `<ベース名>.<画像拡張子>` が両方そろったものだけを対象にする（`.part` は無視）。
- `adb pull` でJSON→画像の順に `incoming/` の `.part` へ取り出し、大きさを確かめてから正式名へリネーム。取り出しに成功したら `adb shell rm` で端末側の2ファイルを消す。
- adbの場所: 環境変数 `ADB` → `PATH` → `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe` の順に探す。見つからなければ理由を表示して終了する。
- 起動: `venv\Scripts\python.exe -m manager.usb_pull`（`--interval`、`--incoming`）。`adb` を呼ぶ部分は関数に分け、テストでは偽物に差し替える。

> [!warning] 最初に実機で確かめること（実装の前提）
> Android 11以降、`Android/data` 配下は他のアプリから見えないが、`adb shell` からは読み書きできる前提で設計している。SO-52E（Android 15）で
> `adb shell ls /sdcard/Android/data/jp.sotuken.metercapture/files/` と `adb pull` が通るかを**段階3の最初に**確認する。通らなければこの節を設計し直す。

## 4. スマホ側

### 4.1 送信先の設定（最小限）

- 画面に「送信先の設定」を1つ追加する: 送信先URL（例 `http://192.168.1.20:8765`）と合言葉。`SharedPreferences` に保存する。
- URLのホストがプライベートIPv4でなければ保存しない（理由を表示）。
- 平文HTTPを許すため `res/xml/network_security_config.xml` を追加し、`base-config` で `cleartextTrafficPermitted="true"`。任意のLAN内IPを事前に列挙できないため。代わりに、上のプライベートIPの検査をアプリ側で必ず行う。

### 4.2 `HttpSender`（`TODO()` を実装）

- 依存を足さず `HttpURLConnection` で作る。`GET /health`（接続2秒・読み取り3秒で打ち切り）と `POST /upload`（3.1のヘッダー形式。サイドカーの中身は `FolderSender` と同じ項目）。
- 200なら成功。それ以外・例外は失敗として `Result.failure` を返す（理由の文字列付き）。

### 4.3 `QueueSendWorker`（`TODO()` を実装）

1回の実行で次を行う。
1. `recoverInterruptedSends()`（送信中のまま止まった項目をPENDINGへ戻す。既存）。
2. PENDINGの項目を古い順に取り出す（`QueueDao` に `findByState` を追加）。
3. 送信先が設定済みで `GET /health` が通れば、各項目を `markSending` → `HttpSender.send` → 成功なら `markSent(via = HTTP)`。失敗したらその項目は送信箱へ回す。
4. 受信口に届かないときは、各項目を `markSending` → `FolderSender(outbox).send` → 成功なら `markSent(via = FOLDER)`、失敗なら `markFailed`（例: 空き容量不足）。
5. **送信箱に残っている項目の追い送り**: `via = FOLDER` で、送信箱のファイルがまだ残っている（＝USBでまだ吸い出されていない）項目は、受信口に届くならHTTPで送り直し、成功したら送信箱のファイルを消して `via = HTTP` に書き換える。
6. 予期しない例外は `Result.retry()`（指数バックオフ）。

起動のきっかけ:
- 撮影してキューに入れた直後に、一意の作業名 `queue-send` で `OneTimeWorkRequest` を `ExistingWorkPolicy.APPEND_OR_REPLACE` で登録（条件なし。送信箱への書き出しは圏外でもできるため）。
- アプリ起動時に1回。
- ネットワークにつながったときの追い送り用に、`NetworkType.CONNECTED` 条件付きの定期作業（15分ごと、一意名 `queue-send-periodic`、`KEEP`）。

### 4.4 キューの項目に「どの経路で送ったか」を足す

- `QueueItem` に `sentVia: String?`（`"http"` / `"folder"`、未送信はnull）を追加する。Roomのバージョンを1→2に上げ、`ALTER TABLE queue_items ADD COLUMN sentVia TEXT` のマイグレーションを書く（既存の端末のキューを消さないため。破壊的マイグレーションは使わない）。
- `markSent(localId, via)` に変える。既存の呼び出しとテストも合わせる。
- SKくんのSK-06（リスト画面）で「送信済み（無線）」「送信済み（USB待ち）」を出し分けられるようになる（SK-06では表示するだけ。キュー側の変更は本人担当）。

### 4.5 触らないもの

- 撮影画面とガイド枠（SKくん担当の `ui/`）。送信先の設定画面だけは追加してよいが、既存の撮影画面の配置は変えない。
- `allowBackup=false` などの既存の安全設定。
- 送信済み画像の保持期間（O-07）。今回は消さずに残す。

## 5. 段階と受け入れ条件

| 段階 | 内容 | 受け入れ条件 |
|---|---|---|
| 1 | PCの受信口（3.1）と `app.py` での表示 | 単体テスト（一時フォルダ・空きポートで本物のサーバーを立てる）: 正常アップロードでJSON→画像の順に正式名で置かれる、合言葉違いで401、SHA-256違いで400、ファイル名不正で400、同名再送で200 duplicate、プライベートIP以外で403（判定関数を差し替えて確かめる）。既存テストがすべて通る |
| 2 | スマホのHttpSender・Worker・設定・マイグレーション（4.1〜4.4） | JVMテスト: JDK付属の `com.sun.net.httpserver` で受信口の偽物を立て、HttpSenderの成功・401・切断を確かめる。偽のSenderでWorkerの経路選択（届く→HTTP、届かない→送信箱、HTTP失敗→送信箱、追い送り）を確かめる。`:app:testDebugUnitTest` と `:app:assembleDebug` が通る |
| 3 | USB自動吸い出し（3.2） | 最初に実機で前提（3.2の注意）を確かめる。偽のadbで、そろった組だけ取り出す・`.part`を無視・取り出し後に削除・adbが無いときの表示、をテスト |
| 4 | 通しの確認（実機、大久保） | (a) 同じWi-FiでPCが `app.py` を起動中: 撮影→1分以内に一覧に出る。(b) Wi-Fiを切って3枚撮影→USBで接続→自動で吸い出され一覧に出る。(c) (b)のあとWi-Fiに戻すと、まだ吸い出していない分が無線で届く。(d) 同じ写真が二重に登録されない |

各段階は別々のPRにする。段階1と3はPython、段階2はKotlin。

## 6. 未決事項

- ポート番号（8765で始める）
- 受信口を `app.py` 起動と一緒に動かす既定をオンにするか（この仕様ではオン）
- `watch_inbox.py` と `usb_pull.py` も `app.py` から一緒に起動するか（この仕様では別起動。まとめて起動する案は、通しが動いてから検討）
