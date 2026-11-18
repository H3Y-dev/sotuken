# React本移行の統合と機器登録

## 未確定事項

- ADB接続でUSB用の既送信ペアを再配置できる本番端末かを確認する。不足した場合は未測定とする。
- `feat/qr-unit-range-link` の差分は参照できなかった。step3の `build_payload` には既に `unit/min/max` がある一方、`create_label_image` と `make_label_sheet` はIDと機器名しか渡していない。合流時にラベル入力の型と欠損範囲の扱いを照合してから、PDF実装に進む。
- 機器登録の許容範囲は本設計で両端を含む。目盛り範囲が未設定でも許容範囲を保存できる仕様を採用する。現場で別の制約が必要なら機器登録の着手前に確定する。

## 1. step3と計器盤の統合

基準は step3 `8ec6603` と計器盤 `312e849`。共通祖先は `7fd3ffc`。以下は共通祖先から両側で変更されたファイルの全件。Gitの自動衝突に限らず、意味上の衝突も含めた。パスはすべて `prototypes/react-records/` 基準。

| ファイル | 採用する側と統合結果 |
|---|---|
| `.gitignore`、`.oxlintrc.json`、`components.json` | step3 |
| `DESIGN.md` | 計器盤。機器登録の配色、書体、罫線の正本とする |
| `index.html`、`public/favicon.svg`、`public/icons.svg` | step3 |
| `package.json`、`package-lock.json` | step3。Geistは既存依存を使う |
| `src/App.tsx`、`src/main.tsx` | step3。既存の記録・接続設定と同じ一つのアプリに「機器登録」を足す |
| `src/api/client.ts`、`src/api/types.ts` | step3。実APIクライアントに機器登録を追加 |
| `src/components/Choice.tsx`、`src/components/OverlayPreview.tsx` | step3 |
| `src/components/ui/alert.tsx`、`badge.tsx`、`button.tsx`、`card.tsx`、`checkbox.tsx`、`collapsible.tsx`、`input.tsx`、`select.tsx`、`table.tsx`、`toggle-group.tsx`、`toggle.tsx`（後続ファイルも同ディレクトリ） | 各step3 |
| `src/index.css` | step3。機器登録のトークンは画面内にスコープする |
| `src/lib/download.ts`、`records.test.ts`、`records.ts`、`utils.ts`（後続ファイルも同ディレクトリ） | 各step3 |
| `tsconfig.app.json`、`tsconfig.json`、`tsconfig.node.json`、`vite.config.ts` | 各step3。既存の静的配信構成を維持 |

step3だけにある `src/components/{QrCodeSvg,RecordsView,SettingsView,StatusBadge,TrendChart}.tsx` は残す。①では計器盤の `src/gauge/gauge.css` の色・寸法を機器登録のCSSへ移す。計器盤の画面・判定部品を取り込むのは②で、その時に `Dial.tsx`、`GaugeHome.tsx`、`GaugeDetail.tsx`、`judge.ts`、`judge.test.ts`、`status.tsx`、`gauge.css` を個別に確認し実データに接続する。計器盤側の `GaugeApp.tsx`、`src/mock/`、`src/astryx/`、`App.css`、`src/assets/`、`src/components/ui/{chart,number-ticker}.tsx`、`README.md`、`screenshots/` は①の配信に入れない。

統合作業の起点を `feat/react-production-integration` とする。Reactでの開発推進は確定済みのため、統合ブランチで最新 `origin/main` を取り込み、step3に対する回帰確認を済ませてmain向けPRを作る。計器盤ブランチを丸ごとマージすると実APIと画面の入口を置き換えるため、上表で指定したファイルだけ採用する。mainへの順序は「配信基盤＋デザイン正本 → セッション → ① → ② → ③ → ④」。配信基盤PR（PR1）は、検証用の起動に限りStreamlitを残したまま③（実機USB 10回）を待たずにmainへ入れる。本番切り替え（Streamlit停止）は、第2節の実機USB 10回（担当: SR）と①の受入完了後に別判定で決める。QRメンバーのPRは①のPDF PRより先に合流する。

## 2. 実機試験（担当: SR）

### 試験環境

1. PCの同じPython環境と同じスマホを使用。別フォルダ `C:\sotuken-e2e\react-usb` に `8ec6603` の作業用コピーを用意する。コピーは `git archive --format=zip --output=C:\sotuken-e2e\step3.zip 8ec6603` の出力を展開する。独立した `manager.db`、`incoming`、`images`、`overlays` を使い、PCの稼働中データは使わない。
2. コピーの `manager/pc_config.json` に試験用受信設定を用意し、スマホを試験先へ接続する。トークンは記録表へ転記しない。Pythonの依存、使用する認識モデル・設定、スマホAPKの版をそろえる。USB試験中はスマホのWi-Fiと携帯データを切る。試験用スマホの既存キューとoutboxは事前に確認し、試験項目だけが流れる状態にする。
3. 対象コピーのルートから次を実行し、監視プロセスのPIDを控える。DBファイルができ、監視フォルダと保存先がコピー内であることをログで確認する。watcherを二重起動しない。

```powershell
python -u -m manager.watch_inbox --watch-dir incoming --db manager.db --images-dir images --overlays-dir overlays
```

4. 同じコピーの別端末で以下を実行し、手動で `http://127.0.0.1:8766/` を開く。現行ランチャーはブラウザを開かない。 `<PID>` は手順3で控えた数値に置換する。接続設定から記録に戻れることを確認する。

```powershell
python -m pc_api.launcher --db manager.db --incoming-dir incoming --images-dir images --overlays-dir overlays --static-dir pc_api/static --port 8766 --owner-port 8767 --no-streamlit --watch-inbox-pid <PID> --usb-pull
```

### HTTPから行・画像が表示されるまで（基準外・未測定）

同一写真の再送手段と共通時計が無いため、基準から外し未測定とした。結果記録は「未測定（理由: 同一写真の再送手段と共通時計が無い）」とする。

### 物理USBの抜き差し10回

実施担当: SR。

1. Reactの接続設定でUSBが有効なのを確認する。ブラウザ開発者ツールのネットワークで画面が取得する `GET /api/v1/runtime` と `GET /api/v1/usb/status` の応答から `owner_instance_id`、`observed_at`、`pulled_total`、`cycles` を読む。最初に試験用の写真1枚とサイドカーを取り込み、同一名のペアを試験用に保存する。基準累計を B とする。
2. 各回でケーブルを抜き、`adb devices` で対象シリアルが消えるのを確認する。切断中に固有写真1枚を撮り、USB転送用outboxに入ることを端末で確認する。既送信ペアの再投入が可能であれば、再接続時に同じ内容・同じファイル名のペアも1組置く。対象は `/sdcard/Android/data/jp.sotuken.metercapture/files/outbox`。ADBで書き込める場合は `adb -s <serial> push <json> <outbox>/`、続けて `adb -s <serial> push <image> <outbox>/` を実行する。各プレースホルダーは確認した実値で置換し、画像を最後に配置する。配置のタイミングで別サイクルに分かれた場合も、両方の処理を待って記録する。既送信ペアの再投入ができなかった回は正本第6節の条件を未測定とする。
3. 接続後、`adb devices` で同じシリアルが `device` に戻ったことを確認。接続設定の最新応答を読み、watcherの保存結果と照合する。各回の上限は再接続から60秒。超過時の再起動で結果を上書きせず、その回を失敗として残す。USBサービスが数えるのは処理済みペアであり、既送信ペアも正常処理されれば加算される。期待累計は2ペアを毎回処理できたとき `B + 2 × 回数`、最終値 `B + 20`。
4. 試験コピーのルートで `python -m sqlite3 manager.db "SELECT image_sha256, COUNT(*) FROM meter_readings GROUP BY image_sha256;"` を実行する（Python 3.12以上）。最初の既送信写真は1行のまま、固有写真10枚は各1行、追加は計10行。既送信ペアはUSBログの「既に受信済みのためスキップ」か、watcherログの「処理済みのため推論を飛ばした」で確認する。新しい認識処理も保存行の追加も0件とする。各回の復帰、同じowner、期待累計、新規10枚の保存、重複処理・重複保存ともに0件で合格。USB累計をDBの追加件数として扱わない。

| 回 | 切断 / 復帰時刻 | owner ID | 基準 / 前回累計 | 期待 / 実測累計 | 新規写真ID / SHA-256 | 既送信ペア処理 | 各ハッシュの行数 | 重複処理 / 保存 | 判定 |
|---|---|---|---|---|---|---|---|---|---|
| 1〜10 | | | | | | | | | |

本番切り替え（Streamlit停止）は、①固定データ一致（自動試験合格済み）、②a DB確定から画面表示まで5秒以内（自動E2E最大4.845秒で合格済み）、③本節の実機USB 10回（担当: SR）の3条件および本移行①（機器登録）の受入完了をもって判断する。②bは基準外・未測定（理由: 同一写真の再送手段と共通時計が無い）として記録する。

## 3. セッションの導入時期

Go後、①で書き込みAPIを公開する前に入れる。先に共通の認証境界を作れば、機器登録だけに検証用トークンによる書き込みを足す必要がなくなる。Go試験は比較対象のstep3を固定したまま行う。

対象は `pc_api/server.py`、`pc_api/launcher.py`、Reactの起動処理とAPIクライアント。正本第9節の `/session` を既存API接頭辞に合わせ `/api/v1/session` に置く。POSTは同一OriginのJSON `{launch_key:string}` を受け、ランチャーがfragmentで渡した一回限りの60秒鍵を定数時間比較で交換する。画面はfragmentを読み取った直後に `history.replaceState` で消す。応答は200 `{csrf_token:string}` とHttpOnly、SameSite=Strict、Path=/のセッションCookie。GETは200でCSRFトークンを復元し、DELETEは同一Origin・CSRF付きで204、Cookie削除とサーバー側失効を行う。期限は8時間またはAPI終了の早い方。失効・期限切れ・無効鍵は401 `unauthenticated`。Origin・CSRF不一致は403 `forbidden_origin`。既存のPC側読み取りと画像取得、pairing変更にも共通境界を適用し、スマホ受信口とowner内部認証は従来どおり。HTMLへのPCトークン注入を削除する。カーソルと60秒スナップショットは履歴のページングを本番化する②で扱う。①の一覧契約は下記の上限付き全件取得とする。

既知の制約（2026-11-18 メイン判断）: Cookieはポートで分離されないため、`pc_session` は同じ `127.0.0.1` の別ポート（受信口8765・owner 8767）にも送られる。いずれも本システムの自前サービスでCookieを記録・利用しないため受け入れる。外部のサービスを同じPCの `127.0.0.1` で動かす運用になったら、PC画面に専用のホスト名を割り当てる。

## 4. 機器登録とQRラベル

### DBとAPI

`manager/storage.py` の現行初期化トランザクションで `devices` の列を調べ、欠けている `tolerance_min REAL`、`tolerance_max REAL` を追加する。新旧DBとも既定NULL。既存の機器・読取行、取り込み時の空欄補完ルールを維持する。書き込み先はランチャーと同じDB。API起動時に耐久データの新規作成を暗黙に行わず、ランチャーが既存DBを確認した後でスキーマを更新してから配信する。

`DeviceInput` は `{device_name:string,unit:string|null,min_value:number|null,max_value:number|null,tolerance_min:number|null,tolerance_max:number|null}`。全キー必須。 `Device` はこれに `{device_id:string,provisional:boolean}` を加えたもの。DBの `kind/note/created_at/updated_at` は今回の画面の入出力から省き、既存値を維持する。公開JSONは既存のエラー包絡 `{error:{code:string,message:string,request_id:string}}` を使用。

| メソッドとパス | 入力と成功応答 |
|---|---|
| GET `/api/v1/devices` | クエリなし。200 `{items:Device[]}`。IDのSQLite BINARY昇順。1,001行目を検出したら422 `validation_failed`。空は `{items:[]}` |
| POST `/api/v1/devices` | JSON `DeviceInput & {device_id:string}`。201 `Device`。人手による新規登録は `provisional=false` |
| PUT `/api/v1/devices/id-{device_id}` | JSON `DeviceInput` で編集項目を全置換。200 `Device`。名前変更とNULLへのクリアを許可。暫定登録も保存成功で `provisional=false` |
| POST `/api/v1/devices/labels.pdf` | JSON `{device_ids:string[]}`。1〜50件、重複不可。入力順にA4縦（2列×5段）。200 `application/pdf`、`Content-Disposition: attachment; filename="device-labels.pdf"`、`Cache-Control: no-store`。1件でも未登録なら全体404 |

- IDは既存 `validate_device_id` と同じASCII 1〜32文字。前後の空白は拒否。PUTは固定接頭辞 `id-` を外し、一度デコードしてIDを検証する。既存の有効ID `.`、`..`、`labels.pdf` も編集できる。
- 機器名は既存 `validate_device_name` で正規化し1〜64コードポイント。 `unknown` は予約値として拒否。単位は前後の空白除去後1〜16コードポイント、UnicodeカテゴリCを拒否。空欄は画面でNULLに変換する。
- 数値は有限のJSON numberかNULL。真偽値、数値文字列、NaN、無限大は拒否。目盛り範囲は両方NULLまたは `min_value < max_value`。許容範囲は両方NULLまたは `tolerance_min <= tolerance_max`。目盛り範囲がある場合は許容範囲をその内側に収める。目盛りの最小・最大と許容端点の一致は可。
- 未知キー・重複JSONキー・欠落キー・不正JSON・不正クエリは400 `invalid_request`。値や型が不正なら422 `validation_failed`。セッションなしは401、Origin・CSRF違反は403。ボディはUTF-8の `application/json` のみ、上限16,384 bytes、超過413 `too_large`。更新先やPDF対象がなければ404 `not_found`。新規IDが完全一致または大文字小文字だけ異なる既存IDと衝突したら409 `device_conflict`。既存の大小文字違いはPUTで完全一致の行を個別編集する。SQLiteロックは503 `db_busy` と `Retry-After: 1`、内部エラーは500 `internal_error`。PUTは末尾スラッシュなし。
- `manager/devices.py` の `list_devices(storage, *, limit=None)` は既存呼び出しの全件取得を維持。 `create_device(storage, device_id, fields)` と `update_device(storage, device_id, fields)` は `fields:dict` とDB辞書を受け渡し、前者は衝突時 `DeviceConflict`、後者は不在時 `KeyError`。入力検証は `validate_device_fields(fields:dict) -> dict`。作成と更新は `BEGIN IMMEDIATE` 内で検索・変更・結果取得を完結。更新には内部の `_update` を使う。 `register_device` の空欄補完はそのまま再利用され、手動更新の代用には使わない。更新は表示された項目の全置換で、同一機器を別タブから保存した際は最後の保存が反映される。
- `pc_api/server.py` の `dispatch(self, method, target, body=None)` に解析済みJSONを渡し、機器処理を `pc_api/device_routes.py` の `dispatch_devices(storage, method, path, body)` に置く。応答の既存形式 `(status, body, mime)` を維持。ハンドラーは成功したPDFのパスにだけ添付ヘッダーを付ける。GETで同じDBを読む経路は書き込みを伴うスキーマ初期化を繰り返さない。

### PDFとメンバーの変更への依存

`build_device_label_pdf(storage, device_ids:list[str]) -> bytes` を `pc_api/device_labels.py` に置く。要求された機器を一つのDB読み取りで取得し、見つからないIDがあれば生成前に404。DBの機器ID、名称、単位、目盛りの最小と最大を `manager/qr_label.py` のラベル生成経路に渡す。合流時の入力署名は上記の未確定事項として扱う。期待するQR本文は `build_payload(device_id, name, unit=unit, min=min_value, max=max_value)`。NULLはキー省略。許容範囲はPDF生成の引数、印刷面、QR本文のいずれにも渡さない。既存のA4シート生成を使用し、サーバー側の `TemporaryDirectory` 内の固定名へ出力して読み戻す。クライアントは保存パスを指定できない。生成後は一時領域を解放し、失敗時には部分PDFを返さない。既存レコードの名称・単位・目盛りがラベル入力契約を満たさない場合は422とし、機器の編集を促す。

QRブランチの合流前にセッション、DB、一覧・登録・更新API、機器画面を進められる。PDFボタンの配線と、単位・目盛りのQR往復検証は合流後。保存側の `tolerance_min/max` はQR側の `min/max` と別の列であり、合流前のDB設計を妨げない。

### React

- `src/App.tsx` に「機器登録」タブを追加。 `src/components/DevicesView.tsx` の `DevicesView()` に一覧、追加・編集フォーム、PDF用チェック欄を置く。 `src/api/types.ts` へ `DeviceInput`、`Device`、 `src/api/client.ts` へ `listDevices():Promise<Device[]>`、`createDevice(input:DeviceInput & {device_id:string}):Promise<Device>`、`updateDevice(id:string,input:DeviceInput):Promise<Device>`、`downloadDeviceLabels(ids:string[]):Promise<Blob>` を追加する。PUTパスは `/api/v1/devices/id-` に `encodeURIComponent(id)` を連結する。
- 見出しは「機器登録」。表は選択・機器ID・機器名・単位・目盛り範囲・許容範囲・編集の順。NULLは「未設定」。追加フォームでID入力可、編集でIDは読み取り専用。名称以外のフォーム項目は単位、目盛り最小・最大、許容最小・最大。入力フィールドにラベルとエラーを関連付ける。自由入力の空白数値はNULLにし、有限数だけを送る。
- 初回読み込み中は表に「読み込み中」、空は「登録済みの機器はありません」、失敗は「機器一覧を取得できませんでした」と再読込ボタン。追加・編集は表の上のフォームで行う。保存中は送信・キャンセル・編集切替を無効化。成功時は応答の行で表を更新しID順に並べ直してフォームを閉じる。失敗時は入力値を保持。409ではID衝突、422では入力確認、401ではアプリの再起動による再認証を表示する。通信失敗の書き込みを自動再送しない。
- PDFはチェックしたIDを表の順に渡す。0件または51件以上ならボタン無効。選択件数と「最大50件」を表示。生成中はボタンを無効にし、成功時は`src/lib/download.ts` の `download(name:string,text:string|Blob,type:string)` を使って `device-labels.pdf` を保存する。失敗時は選択を保持する。PDF未接続のPR時点ではボタンを表示しない。
- `src/components/devices.css` の `.devices` に計器盤と同じ盤面 `#e3e6e4`、表・フォーム `#f8f8f5`、文字 `#1c2226`、主ボタン・フォーカス `#1d3a63`、入力枠 `#757f85`、エラー `#a23b24`、角丸4px。本文は system-ui と Yu Gothic、数値は等幅書体と等幅数字を使う。現行の静的配信はフォントファイルを許可していないため、①は別フォントの配信を追加しない。版面は最大1280pxで中央、余白24px。960px未満では余白16px、フォームを1列、表は横スクロール。既存 `Button/Input/Table/Checkbox/Alert` を利用。アニメーション、値のカウントアップ、画面遷移演出を入れない。

## 5. PR単位の作業

各PRはテストを含む手書き差分約300行を目安とする。既存資産の取り込み差分と静的バンドルの生成差分は別集計にし、内容と生成元を照合する。前段PRがそろうまでは同じ統合ブランチ上の直前PRをベースにする。

| PR | 触るファイル | 受入条件 |
|---|---|---|
| 1 配信基盤 | step3の既存差分、`prototypes/react-records/DESIGN.md` | main側の変更を取り込んだ上で既存の記録・設定と静的配信の回帰なし、`python tools/verify_react_migration.py` 合格（検証用の起動に限りStreamlitを残したまま③を待たずに入れる）。既存実装取り込みなので300行の対象外 |
| 2 セッションのサーバー側 | `pc_api/server.py`、`pc_api/session.py`、`tests/test_pc_session.py` | 鍵再利用・期限切れ・異Origin・CSRF欠落を拒否。次PRの有効化まで現行起動を維持 |
| 3 セッションの起動と切替 | `pc_api/launcher.py`、`pc_api/server.py`、`src/main.tsx`、`src/api/client.ts`、`tools/verify_react_migration.py`、`pc_api/static/` | fragment消去、再読込、失効を確認。旧PCトークン埋め込みを削除。記録・画像・設定のE2E合格 |
| 4 機器DB | `manager/storage.py`、`manager/devices.py`、`tests/test_device_admin.py` | 既存DBを続けて二度開ける。既存機器を保持し、衝突拒否・項目クリア・取り込みの空欄補完を確認 |
| 5 機器API | `pc_api/launcher.py`、`pc_api/server.py`、`pc_api/device_routes.py`、`tests/test_pc_devices.py` | 一覧・登録・更新のHTTP契約と不正入力・認証・並行登録を確認 |
| 6 機器画面 | `src/App.tsx`、`src/api/{client,types}.ts`、`src/components/DevicesView.tsx`、`src/components/devices.css` | 実APIから一覧表示、追加・変更・空欄化。通信失敗時に入力保持。キーボードで全操作可 |
| 7 PDF API | `pc_api/{server,device_routes,device_labels}.py`、`tests/test_pc_device_labels.py` | QR側合流後に実施。1件・10件・11件・50件、51件拒否、重複・不明ID拒否。ラベルを読み戻して単位・目盛り一致、許容範囲のキーなし |
| 8 PDF操作と配信 | `src/api/client.ts`、`src/components/DevicesView.tsx`、`src/lib/download.ts`、`pc_api/static/` | 0・51件で無効、印刷用PDFを保存できる。ランチャー起動から作成・更新・ダウンロードの全経路を確認 |

PR表の `src/` は `prototypes/react-records/src/`。各PRでリポジトリルートから `python -m unittest discover -s tests -q` を実行。Reactに触るPRでは次の3コマンドを個別に実行し、終了コードが0であることを確認する。配信PRでは `npm run build` の出力 `prototypes/react-records/dist/` から `index.html` と参照先の生成ファイルを `pc_api/static/` に反映し、旧ハッシュ名の生成ファイルを除く。ランチャーから配信した画面で、記録・設定・機器登録を確認する（該当PR時点で存在する画面を対象とする）。統合基盤とセッション切替で `python tools/verify_react_migration.py` を実行する。

```powershell
Set-Location prototypes/react-records
npm test
npm run lint
npm run build
```
