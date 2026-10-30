# 機器ID設計 レビュー（Argon）

`id`主キー＋`reading_id` UNIQUEの案Aや、S0・B1先行のタスク分割は妥当である。
ただし再処理時の1撮影1行規則、スカラー限定での診断消失、B1〜B6の時刻・相対パス保存漏れなど実装前に塞ぐべき穴がある。
2人体制の初版に合わせ、点検2表は見送りmanifest方式とし、以下の指摘を設計書へ反映することを勧める。

## 1. 【高】

- **【高】1.主キー（L9,64,74,111,136,149,176）** 何が：再処理（`reprocess.py:20-47`）で同ハッシュが複数行になるが②⑤の1撮影1行規則が無く新列も引き継がない。L136（`id`）とL176（`reading_id`）も矛盾。なぜ問題か：②重複・⑤二重計上・ID消失が起き、`storage.py:282`は同版重複を防げず旧行重複等でUNIQUE索引が失敗。直す案：`COALESCE(image_sha256,'id:'||id)`の最大`id`採用、新列引継、NULL・重複を`legacy:<id>`で埋める。
- **【高】6.ログ縮小（L80,99-100,192）** 何が：ログと`raw_data_json`を「スカラーだけ・配列は長さ置換」とする。なぜ問題か：6.2GBの原因は`storage.py:11`除外の`processed_img`を`ingest.py:113`が書いた点。この規則では`meter_pipeline.py:96-102,175`座標が`2`になり`scale_diagnostics`（`scale_value_detect.py:1040`、1〜3KB）も消える。直す案：`processed_img`・`ticks`のみ除外し座標と診断辞書を残す。
- **【高】2・7.撮影時刻とタスク（L56,82,116-119,193-198）** 何が：新列（`captured_at`・`received_at`・`image_rel`・版）保存がB1〜B5に無く、`captured_at` NULL時の期間・順序も未定義。なぜ問題か：`ingest.py:139`が`sidecar.py:14`時刻等を保存せずB6で`export.py:16,52`別名を消すと日時空や例外になりNULL行の脱落・逆転が起きる。直す案：B1で`storage.py:28-254`対応、B4でUTC化、B5で両時刻（後着と`incoming/`の`mtime`）・相対パス・版を保存。比較は`COALESCE(captured_at,received_at,timestamp)`＋`id DESC`、表示は`captured_at`。
- **【高】5.取込順序と同一性（L154-170,195-197）** 何が：6章「2.無ければ画像QR→4.違えば`id_conflict`」、B3複数QR、後着・再送に穴。なぜ問題か：①2が「無ければ」だと4に届かない。②`detectAndDecode`は単一QRのみで非機器QRも数えると`qr_multiple`になる。③後着（`ingest.py:37-62`）で`qr_not_found`消去・`devices`登録が抜けNULL後着で`id_conflict`になる。④`receiver.py:298`・`usb_pull.py:200`は同名画像で後着JSONを捨て、`watch_inbox.py:73`＋`watcher.py:152`は起動毎に後着再実行、`"unknown"`（`ingest.py:21`）でL154が固定化。直す案：①有効サイドカー時は画像QRを読まず（違反は`id_invalid`で画像QRへ）、`id_conflict`は後着異IDのみ。②`detectAndDecodeMulti`で機器QR異ID複数のみ`qr_multiple`、1個は`pc_qr`。③後着有効IDは`issue=NULL`・`devices`登録、NULLは維持。④`"unknown"`はNULL化、`pc_qr`時は`name`保存、取込後に`incoming/`画像を消す。

## 2. 【中】

- **【中】3.点検の記録（L16,147,171-178,193,200）** 何が：`inspections`等2表を提案（`PCインストーラー化.md:18`と矛盾）。なぜ問題か：`reading_id`固定でも名称・単位は`devices`（L120,127）、真値は`image_truths`（`storage.py:199`）結合で後から直せば再出力は変わり初版に重い。直す案：2表は作らず同名`.manifest.json`（期間・`reading_id`と`id`・SHA-256）案（L178）とする。
- **【中】4.単位・目盛り（L15,35,70,80-81,127,183,216）** 何が：単位・目盛を`devices`のみに持ち（L127）、質問9（L216、`先方への確認事項.md:213`）で単位変更を聞く。なぜ問題か：QRの`unit`等は任意（L35）で旧行もNULLになり範囲も`raw_data_json`（L80）・`devices`・`image_truths`の優先順が曖昧。`sync_devices.py`（L183）で過去単位が変わり質問9が2の現場と矛盾。直す案：NULLは`""`、範囲は`devices`＞`image_truths`＞`raw_data_json`、質問9が2なら`unit`列か枝番IDと注記。
- **【中】7.タスク分解（L184,190-200）** 何が：S0・B1先行と5ファイル以内は妥当だがB4・B6依存とB1退避（L184,193）が不整合。なぜ問題か：B4（`sidecar.py`）はB2（`devices.py`）検査を使い違反を`None`にするとB5で未入力と`id_invalid`を区別できない。B6（`export.py`）はB2・`storage.py`依存が抜け、B1退避は`PCインストーラー化.md:19`と矛盾し`storage.py:54`毎に走る。直す案：退避を削りB4はB2依存（`issue`保持）、B6にB2・`storage.py`を足す。

## 3. 【低】

- **【低】8.出力（L56-68）** 何が：①②の列定義。なぜ問題か：①不足：②履歴（L66）に`現場入力値`・`備考`が無く手入力値が欠落。②ミス：L60は`現場入力値=38.5`・測定値空で`測定方法=自動`（`record.py:37`では手動）、L61は`備考`に「範囲外の疑い」を混在。③過剰（推測）：②の`機器番号の出所`・`処理版`は過剰（推測）、2表見送りなら①点検IDも冗長（`PCインストーラー化.md:20`と矛盾）。直す案：②に`現場入力値`・`備考`を足し、出所・版・`issue`はJSONL等へ移す。L60を`手動`へ直し警告は`備考`と分ける。
