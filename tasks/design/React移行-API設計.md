# React移行検証のAPI・プロセス設計

基準コミット: `7fd3ffc1248f9418218e7ace0ea60c372679a9ce`  
検証ブランチ: `exp/react-migration` / 設計日: 2026-11-12

## 1. 範囲と根拠

本書は実装前の提案である。「確認済み」は基準コミットのコードから確認した事実、それ以外のAPI・構成・試験名は新規設計を示す。試験結果や性能の保証ではない。

最初の検証は、実受信→既存取り込み→DB→一覧・元画像とオーバーレイ表示、QR期限切れ、USB切断・再接続に限定する。既存の画面内で検証し、画面を追加しない。DBスキーマ、読み取りアルゴリズム、取り込み・重複判定規則、スマホ側契約は変更しない。6画面の全面移植、WebSocket、遠隔PC管理は非目標。React採用はGo判定後に決める。

### 確認済みの事実

| 根拠（ファイル:行） | 確認内容 |
|---|---|
| `run_pc.py:25`、`:35`、`:43` | 受信口を起動し、オプションでUSBサービスを起動してから同じプロセスでStreamlitを実行する。取り込みプロセスはここでは起動しない。 |
| `app.py:24`、`:47`、`manager/web_pages_ui.py:194` | QRは1秒、USB表示は2秒、記録は自動更新有効時5秒でポーリングする。USBの吸い出し周期そのものは5秒（`manager/usb_pull_service.py:18`）。 |
| `manager/receiver.py:636`、`:649`、`:653`、`:661` | ペアリング操作はサーバーオブジェクトのメソッド。期限判定はmonotonic時計。期限切れ・消費・中止はstatusがNoneになり、理由を区別できない。 |
| `manager/receiver.py:741`、`:757`、`:764`、`:773` | キャッシュはプロセス内。既存受信口を検出するとserver=Noneで返す。受信口は0.0.0.0で待ち受ける。 |
| `app.py:76`、`:79` | 外部プロセスが受信口を所有すると既存画面のQR操作が使えなくなる。 |
| `manager/usb_pull_service.py:78`、`:143`、`:169` | USB状態はロック付き辞書とプロセス内キャッシュ。別プロセスでget_usb_pull_statusを呼んでも所有者の状態は取得できない。 |
| `manager/storage.py:32`、`:81`、`:87`、`:349` | DB行はMeterReading。ファイルDBは都度接続、connectionはトランザクション管理、get_all_readingsで一覧取得。 |
| `manager/manager.py:24`、`:114` | process_imageが手動処理、get_historyがDB履歴取得の入口。 |
| `manager/export.py:18`、`:96`、`:140`、`:160` | 日付・機器名・点検IDの絞り込み、日時正規化、機器名ごとのグループ化、最新採用の既存処理がある。最新採用は名前なしを個別に残し、状態の優先順位でも並べる。 |
| `manager/web_pages_ui.py:223`、`:252` | 既存画面は絞り込み後に最新採用する。集計をページ内の行だけで実施すると一致しない。 |
| `manager/routes.py:29`、`:50`、`:59`、`:65`、`:154`、`:171` | ルート保存・取得・一覧・削除、点検受信状態、撮影進捗の関数が存在する。 |
| `manager/inspection.py:77`、`:98`、`:110` | 点検作成・復元・書き出しの関数が存在する。 |

参考試作はこのworktree外の `C:\卒研\git_stk\sotuken\prototypes\react-records\src\api\client.ts` を確認した。fetchHistoryがダミー全件を返し、filterHistoryがブラウザ内で絞り込む。基準コミットの一部ではなく、サーバーの契約や正解データには使わない。

## 2. 所有者の比較と推奨

| 案 | 利点 | 問題・変更範囲 | 判断 |
|---|---|---|---|
| A: PC APIが受信口とUSBを直接起動・所有 | APIから直接操作できる | 同一プロセスの受信口となり決定済みの別プロセス条件に反する。既存StreamlitのQRもserver=Noneで失われる | 不採用 |
| B: 既存の所有プロセスにローカル専用の管理窓口を置き、PC APIが中継 | 既存画面とReactが同一の実状態を扱える。受信HTTPの権限を拡張しない | 窓口の認証と終了処理が必要。所有者停止時にはAPIが部分的に利用不能になる | 推奨 |
| C: 状態・コマンドを共有ファイルまたはDBで交換 | 表示状態をプロセス外から読める | 古い状態、期限判定、コマンド応答・重複・排他の仕組みが必要。DB変更禁止とも相性が悪い | 不採用 |

Bの窓口をスマホ用の8765番に追加してはならない。新規 `pc_api/owner.py` にループバック専用の別リスナーを置き、既存のserverとUSBサービスを注入する。これは最小限の状態アクセス用の新規コードとする。

```text
スマホ -- X-Sotuken-Token --> 0.0.0.0:8765
                               |
所有プロセス P1: 新規ownerラッパー
  既存ReceiverServer + 既存USBサービス + Streamlit（run_pc.py）
  管理窓口 127.0.0.1:8767（専用内部鍵、状態とQR操作のみ）
       ^
       | 内部鍵。スマホ用トークンとは独立
PC API P2: 127.0.0.1:8766 / API + 同梱React静的ファイル
       ^ 同一origin / PC専用セッション
       | PCブラウザ

受信/USB --> 既存incoming --> 既存watch_inbox P3 --> manager.db
                                                ^
                                   P1とP2から短時間の読み取り
```

ownerは既存初期化関数で受信口と必要時USBを1回起動し、管理窓口を開始した後、同一プロセスで既存run_pc.mainを呼ぶ。run_pc側の再初期化は既存キャッシュを利用する。app.py・run_pc.pyは変更しない。APIは受信口・USB・watch_inboxを初期化しない。取り込みは既存の起動手順を維持する。すべて同一の絶対DBパスとincomingを指すよう、ownerとAPIの作業ディレクトリを明示する。

通常の `run_pc.py --usb-pull` は従来どおり使用できる。検証時だけ停止後にowner経由で同じ画面を起動する。既に通常版が動いていた場合は所有権を奪わず起動を拒否し、停止と起動し直しを案内する。ReactとStreamlitは同時に開ける。ブラウザの画面往復・リロードでサービスを停止しない。

内部窓口はGET /internal/status、GET /internal/pairing、POST /internal/pairing、DELETE /internal/pairingのみ。各応答にowner_instance_idとobserved_atを付ける。開始URLは所有者がinit_receiver_for_appの現在URLから決め、ブラウザ入力のURLを渡さない。URL変更時はapp.py:35と同様に招待を無効にする。招待更新・取得・中止の窓口内操作を直列化し、既存serverのpair_lockも維持する。Streamlitによる操作やスマホの消費は既存ロックで整合し、最後に確定した操作が有効となる。二つの画面が独立したQRを所有する設計にはしない。

所有者停止時はAPIが503 owner_unavailableを返し、QRを即時に隠す。勝手に別の所有者を作らない。owner再起動で招待は消失してよいが、既存DB行は維持する。最終移行でStreamlitを取り外すのは別判断とし、今回の検証には含めない。

## 3. API契約（新規設計）

以下は `/api/v1` 配下。JSONはUTF-8、日時は元のISO8601文字列を保持し、日時比較は既存exportの規則を使う。NaN/InfinityはJSONに出さずnull。raw_data・絶対パス・スマホ用の恒久トークンは返さない。整数DB idをPC内の記録キーとして文字列化し、reading_idとは区別する。

### 共通型とエラー

```text
Reading = {id:string, reading_id:string|null, device_name:string,
 device_id:string|null, captured_at:string|null, timestamp:string|null,
 received_at:string|null, value:number|null, unit:string|null,
 status:string|null, stage:string, confidence:number|null,
 failure_stage:string|null, inspection_id:string|null, inspection_name:string|null,
 route_id:string|null, image_id:string|null, overlay_image_id:string|null}
Page<T> = {items:T[], total:number, next_cursor:string|null}
Pairing = {active:boolean, payload:string|null, expires_at:number|null,
 remaining_seconds:number, owner_instance_id:string, observed_at:string}
UsbStatus = {enabled:boolean, running:boolean, adb_found:boolean,
 devices:string[], pulled_total:number, last_error:string|null,
 interval:number, cycles:number, owner_instance_id:string, observed_at:string}
Error = {error:{code:string, message:string, request_id:string,
 fields?:{[field:string]:string}}}
```

unitなどDBにない属性は既存公開値から取得できる場合のみ設定し、それ以外はnull。状態値を新しい成功/失敗判定に置き換えない。Pairingのinactiveは期限切れ・中止・交換済みを区別しない（既存APIで区別不能）。ブラウザは期限を過ぎたQRをローカルでも隠し、再作成を案内する。

HTTPエラーは400 invalid_request/cursor_invalid、401 unauthenticated、403 forbidden_origin/csrf_failed、404 not_found、409 owner_conflict/stale_snapshot、413 too_large、422 validation_failed、503 owner_unavailable/db_busy。Retry-Afterは503で1秒。内部例外・ファイルパス・鍵をmessageに含めない。リトライはGETのみとし、QR開始や手動処理を通信失敗時に自動再実行しない。

### 最初の検証に必要なAPI

| メソッド・パス | 入力 | 出力 | 対応する既存Python処理 |
|---|---|---|---|
| POST /session | PC専用の一度限りの起動鍵 | `{csrf_token:string}`、セッションCookie | 新規認証処理 |
| GET /session | Cookie | `{csrf_token:string}` | 新規。再読込時の復元 |
| DELETE /session | Cookie・CSRF | 204 | 新規。セッション失効 |
| GET /runtime | なし | `{receiver_running:boolean, receiver_url:string|null, owner_instance_id:string, observed_at:string}` | owner経由init_receiver_for_appの公開状態だけ |
| GET /readings | F、limit、cursor | Page<Reading> | MeterManager.get_history(include_raw=False)→filter_readings |
| GET /readings/{id} | 数字のDB id文字列 | Reading | get_historyからID一致、未登録404 |
| GET /images/{image_id} | IDのみ | image/jpeg または image/pngのバイナリ | DBのimage_path/overlay_pathを新規の安全な解決器で解決 |
| GET /pairing | なし | Pairing | owner経由pairing_status / pairing_payload |
| POST /pairing | 空JSON、CSRF | Pairing | owner経由start_pairing。作成済みなら409、作り直しは明示中止後 |
| DELETE /pairing | CSRF | 204（既に無効でも成功） | owner経由cancel_pairing |
| GET /usb/status | なし | UsbStatus | owner経由get_usb_pull_status。Noneはenabled=false |

F = device_name（完全一致、未指定はすべて）、date_from/date_to（YYYY-MM-DD、両端を含む、逆転は422）、inspection_id（完全一致）。機器名は最大256文字、IDは最大128文字、未知の条件は400。初期検証にない検索・ソート条件は追加しない。日付の境界・タイムゾーンの解釈はfilter_readings/_reading_timeに合わせ、特にオフセット付き日時の境界を試験する。

ページングはカーソル方式、limit既定50、1〜200。初回にget_historyの一貫した読み取り結果を取り、サーバーでFを適用してから、撮影日時（既存の日時解決順）降順・DB id降順で整列する。型変換できない日時は422ではなく503 data_invalidとして記録し、黙って行を除かない。totalは全絞り込み結果の件数。

最初の検証では結果スナップショットをAPIメモリ内に60秒保持する。カーソルはランダムな参照キーと次位置を持ち、セッション・F・limitに紐付ける。上限10スナップショット/セッション、全体100、超過は409 snapshot_limit。期限切れは409 stale_snapshotで先頭を再取得する。同じカーソルは同じ結果を返す。ポーリングは先頭を新規取得し、旧ページのカーソルを破棄する。全件読み込みのメモリと速度は検証上のリスクであり、DBクエリの最適化を先に足さない。固定データの想定上限10,000行で測定し、満たせなければNo-Goとする。

### 後段: 6画面向け（初回には実装しない）

以下もサーバーで絞り込み・集計してからページングする。F・limit・cursorの規則とエラー形式は共通。集計は一つの履歴スナップショットを共有し、ページ断片を集計しない。

| 画面 / メソッド・パス | 入力→出力 | 既存関数・根拠 |
|---|---|---|
| ホーム GET /overview | F→`{total:number, latest:Page<Reading & {display_name:string,status_label:string}>}` | latest_per_device（export.py:160）、load_overview（web_data_ui.py:87）の内容をUI非依存アダプターへ |
| 点検 GET /inspections | limit,cursor→Page<{id:string,name:string,count:number}> | inspection_options（export.py:39） |
| 点検 GET /inspections/{id}/status | id→`{state:string,missing_photos:string[]}` | inspection_status（routes.py:154）、追加フィールドは後段で型を確定 |
| 点検 GET /inspections/{id}/progress | id→`{route_id:string|null,devices:object[]}` | get_manifest、get_route、arrived_manifest_devices、route_progress（routes.py:125/50/163/171）。devices型は後段で実出力に固定 |
| 点検 POST /inspection-reports | `{inspection_id,date_from,date_to,device_ids:string[]}`→`{report_id:string}` | create_inspection（inspection.py:77）。保存先はサーバー固定、最大200機器 |
| 点検 GET /inspection-reports/{id} | id→復元した点検結果JSON | restore_inspection（inspection.py:98）。後段で結果型を固定 |
| 点検 POST /inspection-reports/{id}/export | 空JSON→CSVダウンロード | export_inspection（inspection.py:110）、任意保存先を受け取らない |
| 機器 GET /devices/latest | F,limit,cursor→Page<Reading & {display_name,status_label}> | latest_per_device |
| 機器 GET /devices/series | F,limit,cursor→Page<{device_name:string,points:{at:string,value:number}[]}> | group_by_device（export.py:140）→readings_to_series（:148）。points上限1,000、超過は422で期間短縮を求める |
| 点検・機器 GET /exports/readings | F,format=csv/jsonl→添付ファイル | export_to_csv（:103）、export_to_jsonl（:126）。サーバー内部一時ファイル、最大10,000行、超過422 |
| ルート GET /routes、GET /routes/{id} | limit,cursor / id→Page<Route> / Route | list_routes、get_route |
| ルート POST /routes、PUT /routes/{id} | `{name:string,devices:object[]}`→Route | save_route（routes.py:29）。devicesの既存検証を維持し後段で型を固定 |
| ルート DELETE /routes/{id} | id→204 | delete_route（:65） |
| ルート GET /routes/{id}/qr | id→PNG | route_qr_payload（:71）とQR生成 |
| 接続・設定 | 初回のruntime、pairing、usb/statusを利用 | ポート・恒久トークン変更は再起動を含む別設計まで提供しない |
| 手動 POST /manual-readings | multipart画像1枚（上限20MiB）、既存オプション→Reading | MeterManager.process_image（manager.py:24）。サーバー生成保存名、同時処理1件、超過409 |

後段のobject[]は実装可能な最終契約ではない。各後段タスクで実出力と照合し、Route・点検結果・devicesの具体型と各フィールド上限を本書に追記してから実装する。初回検証にこの曖昧さを持ち込まない。

## 4. 認証・境界・画像配信

PC APIは127.0.0.1:8766だけにbindする。ブラウザも `http://127.0.0.1:8766` に統一し、Hostはこの文字列と完全一致させる。別Host・不正な複数Host・転送ヘッダー経由の書き換えは拒否する。Originは同一originのみ許可し、nullと他originを拒否する。GETのOrigin欠落はCookie認証とHost検証を通す。更新はOrigin必須。CORS許可を返さない。

起動側が暗号学的乱数の一度限りPC起動鍵を生成する。URL fragmentでブラウザに渡し、JSが即座にhistory.replaceStateで消してPOST /sessionのJSON本文で交換する。クエリ・アクセスログ・localStorageに残さない。有効期間60秒、1回限り、照合は定数時間。ローカルの同一OSユーザー権限を信頼境界とし、別ユーザーから読めない場所で鍵を受け渡す。スマホ用X-Sotuken-Tokenを起動鍵として受け入れない。

交換後はHttpOnly、SameSite=Strict、Path=/のランダムCookie。HTTPループバックでのSecure Cookieの挙動に依存せず、ネットワーク公開を禁止する。セッションは8時間またはAPI終了まで。更新はセッションに紐づくCSRFトークンをX-CSRF-Tokenで必須とし、JSON Content-Typeも検証する。POST /session自体は起動鍵・Host・Origin検証で保護する。静的配信には外部スクリプトを禁止するCSP、APIと画像にはno-store、nosniffを付ける。

内部窓口は別の256bit内部鍵を要求する。PC APIのサービス認証専用とし、Cookie・CSRFトークン・スマホトークンは受け入れない。内部HTTPにも厳密なHost検証、Originヘッダー付き要求の拒否、接続元ループバック制限を入れる。内部鍵はAPIとownerの起動時だけ共有し、ブラウザには渡さない。8765側に管理ルートや汎用中継を足さない。

image_idはDB idと種別original/overlayからサーバーが作る不透明ID。IDから当該DB行を引き、保存済みパスのみ使用する。URLやJSONに任意パスを受け取るAPIは作らない。許可ルートは検証用incoming、既存の画像保存先、overlay保存先を起動設定で絶対パスに固定する。resolve後のファイルが許可ルートの配下かをPathの階層で判定し、文字列prefix比較は使わない。UNC・デバイスパス・ADS・親ディレクトリ脱出を拒否し、symlink/junction経由の脱出も拒否する。最終的に開いたファイルの実体も検証し、検査後差し替えを防ぐ。存在しない・範囲外・許可形式外はいずれも404。DB内にパスがあっても無条件には信用しない。

## 5. DB並行アクセスと二重起動

API読み取りではMeterManager/ReadingStorageのコンストラクターを無条件に呼ばない。現行ReadingStorageは初期化時に_init_dbを呼ぶ（storage.py:67）。新規アダプターから既存DBをSQLite URI mode=roで開き、query_onlyを有効にし、get_all_readingsの列対応と同じ公開DTOへ写す。これは新API内の最小限の状態アクセスであり、DDLやマイグレーションを実行しない。

接続は要求またはスナップショット作成ごとに短時間で閉じる。別スレッドで接続を使い回さない。画像配信・HTTP応答・集計中にDBロックを保持しない。取り込みの書き込みを優先し、APIのbusy timeoutは250ms、busy時は503で次周期に再試行する。WALへの切替やスキーマ・既存書き込み処理の変更は行わない。現行DBのjournal_modeを試験時に記録する。後段の更新は既存storage/routes関数の短いトランザクションだけを利用する。

ownerは正規化したDB絶対パスとincomingをキーにOSロックを取得し、管理ポートと受信口の所有を確認する。PIDファイルの存在だけで排他しない。Windowsではファイルロックまたは名前付きmutexのプロセス寿命を使う。USBとwatch_inboxも同じ入力先に対して1所有者のみ。APIも8766のbindと同じDBキーのロックで単一起動にする。既存watch_inboxが外部起動されるため、検証ランチャーで既存の所有者を記録・確認し、二つ目を起動しない。所有者不明の場合は検証を開始しない。取り込み本体へ新しい重複判定は追加しない。

終了はAPI→内部窓口→USB.stop→receiver.shutdown/server_closeの順で行い、ロックを解放する。APIだけの終了でownerや取り込みを止めない。ownerの異常終了ではOSロックが解放され、再起動時は新しいinstance_idと内部鍵を発行する。古い招待・セッション・スナップショットは復元しない。

## 6. Go / No-Goと試験手順

判定値は変更しない。①固定データで件数・値・画像の対応がStreamlit版と一致、②受信が5秒以内に画面反映、③切断・再接続と画面往復を各10回で状態消失・重複処理0件。1項目でも未達・未測定ならNo-Go。失敗写真を結果から除外しない。

5秒ポーリングでは、受信直後に周期が外れ、取り込み時間も加わるため5秒を超える可能性がある。これは未検証の性能リスクである。計測区間をDB確定後へ読み替えず、受信HTTPが成功応答した時刻からブラウザが行と画像を表示した時刻まで測る。初回は5秒のまま測り、超過ならNo-Goとして理由を残し、周期変更は別の合意事項とする。

1. 実DBと分離した固定DB・画像・incomingを用意する。正常、要確認、失敗、値null、名前なし、同名機器、同時刻、日付境界、点検IDあり/なし、元画像欠落、overlayあり/なしを含める。両画面が同じDB絶対パスと画像を参照することを確認する。Streamlitの全件数・絞り込み件数・値・画像ハッシュを基準表として保存する。試験成果物は実装段階の専用ディレクトリへ出す。
2. `test_readings_matches_streamlit_filters`、`test_latest_and_groups_before_pagination`、`test_cursor_snapshot_no_duplicates`で既存export関数との一致とページ全走査の欠落・重複0件を確認する。画像は`test_image_id_maps_to_expected_bytes`でハッシュ照合する。画面側は`test_records_real_api_render`で件数・値・選択画像を確認する。
3. owner、API、watch_inboxを各1つ起動する。実スマホから別々の写真を送信し、受信成功・DB保存・DOM表示・画像loadの時刻と同じ写真IDを記録する。`test_receive_to_render_within_5s`をポーリング直後・直前・中間の各位相で実施し、全件5秒以内を確認する。USBは吸い出し開始から別途計測し、HTTP受信と混同しない。
4. `test_pairing_expiry_hides_qr`は時計を差し替えて期限境界の直前・直後、交換後、中止後、URL変更後を自動試験する。実機でも期限まで待ち、古いQRの交換失敗と再作成後の成功を確認する。消費後の応答喪失も自動再交換しない。
5. `test_usb_disconnect_reconnect_keeps_counts`でAdbRunnerを差し替えた10回の切断・復帰を自動試験する。実機でもUSBを各10回抜き差しし、毎回固有写真1枚と既送信写真を含める。pulled_total、DBの写真ハッシュ、処理回数を照合する。状態は画面のキャッシュでなくownerから取得し、復帰後の正常化を確認する。
6. `test_navigation_10_roundtrips_preserves_runtime`で記録と接続・設定の往復を10回行う。owner_instance_id、QRの期限、USB累計を照合する。招待は期限前の往復で継続し、期限後に消えることを確認する。StreamlitとReactを同時表示してQR中止が両方に反映することも調べる。
7. `test_api_reads_during_ingest`で並行取り込み中の読み取りを実行し、DB busyの回復と欠落0件を確認する。`test_second_owner_rejected`、`test_api_restart_does_not_restart_services`で二重起動と再起動を確認する。
8. `test_reject_phone_token_on_pc_api`、`test_host_origin_csrf_matrix`、`test_image_traversal_symlink_junction_denied`で境界を確認する。Node未導入のWindowsで同梱静的ファイルから起動する試験も必須とする。

自動試験名は提案であり、現時点では未作成・未実行。実機切断やタイミング試験をモック試験の成功で代用しない。期限の具体日と実験に使える時間は依頼文にないため、本書で日付を創作しない。実装開始時に記録し、期限に達した時点で測定済みの結果だけでGo/No-Goを出す。

## 7. 実装タスク（各行を1委任として順番に実施）

| 順序 | 所有範囲と作業 | 受入条件 |
|---|---|---|
| 1 | 新規pc_api/owner.pyと対応試験。管理窓口・既存run_pcの同一プロセス実行・内部鍵・排他・終了処理 | 既存app.py/run_pc.pyを変えず、StreamlitのQR/USBが動く。二重ownerを拒否し、停止時にスレッドが残らない |
| 2 | 新規PC APIの認証・静的配信・内部クライアントと試験 | 127.0.0.1限定、スマホ鍵拒否、Host/Origin/CSRF試験合格。owner不在は503で起動し直さない |
| 3 | 新規読み取り専用アダプター、readings・images APIと試験 | スキーマ差分0、固定データ一致、ページ重複0、画像脱出拒否、並行取り込みを妨げない |
| 4 | pairing/runtime/usb APIと試験 | 期限・消費・URL変更が既存と一致。実状態を中継し、画面からサービスを再起動しない |
| 5 | Reactの既存記録・接続画面とAPI clientのみ接続、静的ビルド同梱 | ブラウザ側で全件の絞り込みをせず、1/2/5秒ポーリングをcleanup付きで実行。新画面0、Nodeなし起動成功 |
| 6 | 結合試験と実機検証、結果表 | 第6節全項目の証拠・時刻・ハッシュ・回数を残し、Go/No-Goを明示。未測定を成功扱いしない |

後段の6画面移植はGo後に、ホーム集計、点検結果、機器推移、ルートCRUD、手動読み取りの順で各1委任に分ける。各委任は具体DTO確定・既存関数との比較・認証/入力検証・当該画面試験までを担当し、他の画面や読み取り本体を変更しない。初回検証の不合格を画面追加で埋め合わせない。

## 8. 設計の限界

本書ではコードの静的確認のみを行った。新構成での同一プロセス起動、Windows排他、5秒以内の反映、実機USB復帰、Node未導入PCでの配布は未検証である。外部技術調査は実施していない。性能・並行動作・配布の可否は第6節の試験で判断する。
