# 機器ID設計 レビュー（Argon）

`id`主キー＋`reading_id` UNIQUEの案Aや、S0・B1を先行するタスク分割は妥当である。
ただし再処理時の1撮影1行の採用規則、スカラー限定による診断消失、B1〜B6での時刻・相対パス保存漏れなど実装前に塞ぐべき穴がある。
2人体制の初版に合わせ、点検2表は見送りmanifest方式へ簡素化し、以下の高〜中の指摘を設計書へ反映することを勧める。

## 1. 【高】（実装前に必須の修正）

- **【高】観点1 主キー（`L9,64,74,111,136,149,176`）** 何が：再処理（`reprocess.py:20-47`）で同ハッシュが複数行になるが②⑤の1撮影1行規則が無く新列も引き継がない。`L136`（`id`）と`L176`（`reading_id`）も矛盾。なぜ問題か：②重複・⑤二重計上・ID消失が起き、`storage.py:282`は同版重複を防げず、旧行の`reading_id`重複等でUNIQUE索引が失敗。直す案：`COALESCE(image_sha256,'id:'||id)`の最大`id`を採用、新列引継、NULL・重複を`legacy:<id>`で埋める。
- **【高】観点6 ログ縮小（`L80,99-100,192`）** 何が：ログと`raw_data_json`を「スカラーだけ・配列は長さ置換」とする。なぜ問題か：6.2GBの原因は`storage.py:11`除外済みの`processed_img`を`ingest.py:113`が書いた点。この規則では`meter_pipeline.py:96-102,175`の座標（`center`等）が`2`になり`scale_diagnostics`（`scale_value_detect.py:1040`、1〜3KB）も消える。直す案：`processed_img`・`ticks`のみ除外し座標と診断辞書を残す。
- **【高】観点2・7 撮影時刻とタスク（`L56,82,116-119,193-198`）** 何が：新列（`captured_at`・`received_at`・`image_rel`・版）の保存がB1〜B5に無く、`captured_at` NULL時の期間・順序も未定義。なぜ問題か：`ingest.py:139`が`sidecar.py:14`の`captured_at`等を保存せず、B6で`export.py:16,52`の別名を消すと日時空か例外で落ち、NULL行の脱落や古い行優先の逆転が起きる。直す案：B1で`storage.py:28-254`対応、B4でUTC化、B5で`captured_at`（後着含む）・`received_at`（`incoming/`の`mtime`）・`image_rel`・版を保存。比較は`COALESCE(captured_at,received_at,timestamp)`＋`id DESC`、表示のみ`captured_at`。
- **【高】観点5 取込順序と同一性（`L154-170,195-197`）** 何が：6章の「2.無ければ画像QR→4.両方違えば`id_conflict`」、B3の複数QR分類、後着・再送に穴がある。なぜ問題か：①2が「無ければ」だと4に届かない。②`detectAndDecode`は単一QRのみで盤面の非機器QRも数えると`qr_multiple`になる。③後着（`ingest.py:37-62`）で`qr_not_found`消去と`devices`登録が抜け、後着IDがNULLで`id_conflict`になりうる。④`receiver.py:298`・`usb_pull.py:200`は同名画像で後着JSONを捨て、`watch_inbox.py:73`＋`watcher.py:152`は起動ごとに後着処理を再実行、`"unknown"`（`ingest.py:21`）登録で`L154`が固定化。直す案：①有効サイドカーID時は画像QRを読まず（違反は`id_invalid`で画像QRへ）、`id_conflict`は後着の異ID時のみ。②`detectAndDecodeMulti`で機器QRの異ID複数のみ`qr_multiple`、1個は`pc_qr`。③後着有効ID時は`issue=NULL`・`devices`登録、NULLは維持。④`"unknown"`はNULL扱い、`pc_qr`時は`name`も保存、取込後に`incoming/`元画像を消す。

## 2. 【中】（初版の設計判断・整合性）

- **【中】観点3 点検の記録（`L16,147,171-178,193,200`）** 何が：`inspections`等2表を提案（`PCインストーラー化.md:18`と矛盾）。なぜ問題か：`reading_id`を固定しても名称・単位は`devices`（`L120,127`）、真値は`image_truths`（`storage.py:199`）結合で後から直せば再出力は変わり初版に重い。直す案：2表は作らず同名の`.manifest.json`（期間・`reading_id`と`id`一覧・SHA-256）を残す案（`L178`）で監査と再出力を満たす。
- **【中】観点4 単位・目盛り（`L15,35,70,80-81,127,183,216`）** 何が：単位・目盛を`devices`のみに持ち（`L127`）、質問9（`L216`、`先方への確認事項.md:213`）で単位変更を聞く。なぜ問題か：QRの`unit`等は任意（`L35`）で旧行もNULLになり、目盛範囲も`raw_data_json`（`L80`）・`devices`・`image_truths`の優先順が曖昧。`sync_devices.py`（`L183`）の上書きで過去記録の単位が変わり質問9が2の現場と矛盾。直す案：NULLは空欄`""`、範囲は`devices`＞`image_truths`＞`raw_data_json`とし、質問9が2なら`unit`列か枝番IDと注記。
- **【中】観点7 タスク分解（`L184,190-200`）** 何が：S0・B1先行と5ファイル以内は妥当だがB4・B6の依存とB1退避（`L184,193`）が不整合。なぜ問題か：B4（`sidecar.py`）はB2（`devices.py`）のID検査を使い、違反を`None`にするとB5で未入力と`id_invalid`を区別できない。B6（`export.py`）は`devices`結合でB2・`storage.py`依存が抜け、B1退避は`PCインストーラー化.md:19`と矛盾し`storage.py:54`ごとに走る。直す案：退避を削り、B4はB2依存（`issue`保持）、B6にB2・`storage.py`を足す。

## 3. 【低】（出力列の整理）

- **【低】観点8 出力（`L56-68`）** 何が：①②の列定義。なぜ問題か：①不足：②履歴（`L66`）に`現場入力値`と`備考`が無く失敗時の手入力値が監査CSVから欠落。②ミス：`L60`は`現場入力値=38.5`・測定値空欄で`測定方法=自動`（`record.py:37`では手動）、`L61`は人のメモ`備考`に判定「範囲外の疑い」を混在。③過剰（推測）：②の`機器番号の出所`と`処理版`は内部情報で過剰（推測）、2表を作らないなら①の`点検ID`も冗長（`PCインストーラー化.md:20`と矛盾）。直す案：②に`現場入力値`・`備考`を足し、出所・版・`issue`はJSONL等に残す。`L60`を`手動`へ直し警告は`備考`と分ける。
