# React本移行の点検確認と計器盤

## 決定事項（2026-11-18 ユーザー）

- **正式CSVの受け取り方**: ブラウザーでのダウンロードだけにする。固定フォルダー（Documents の「メーター点検」）への保存はしない。
- **点検帳票の範囲**: ②の正式CSVは5列CSVだけ。`manager/inspection.py` の期間・機器指定の帳票（`/inspection-reports`）は②に含めず、③以降で扱う。
- **過去のルート構成**: 復元しない。Streamlit と同じく現在の `get_route` を使う。
- **出所と中間工程の表示**: 一覧選択と手入力は「スマホの機器指定」にまとめ、段階3（読み取り済み・記録待ち）は表示しない。
- **合流時の照合**: 配信基盤は main `a1c252c`（PR #144）に入った。①の PR2・3 のセッション連携と PR4 の許容範囲が入ったら、実際のシグネチャ、401・CSRFのエラー、列名、両端の検証を照合する。食い違いがあれば該当PRを止め、差分を設計へ戻す（メインが行う）。

## 1. 前段との接続

①の配信基盤、セッション、機器登録、QRラベルPDFを引き継ぐ。②の点検画面は記録・設定・機器登録と同じ React アプリに置く。局所作業の開始条件は第5節、配信の受入条件は①の PR8 完了。ルート編集と手動読み取りは③・④で扱う。

画面に使うAPIは一覧・受信状態・進捗と5列CSVの4本。全記録のホーム集計 `/overview`、機器別の `/devices/latest`・`/devices/series`、生履歴の `/exports/readings` は本画面から呼ばない。計器盤の一覧は点検単位、推移画面は今回の対象外。API正本の `/inspection-reports/{id}/export` は `export_inspection(inspection, output_dir)` の帳票向けで、正式CSVには専用パスを追加する。正本へのパス追記は PR6 で行う。

## 2. PC API

### 共通契約

- 下表のパスはすべて `/api/v1` 配下。① PR2・3 のループバック・Host・セッション検証を通す。GETはセッションCookie、POSTはさらに同一Origin、`Content-Type: application/json`、セッションの `X-CSRF-Token` を必須とする。ブラウザーからDBパス、受信フォルダー、画像パス、出力先を受け取らない。
- 不正なパスID・未知／重複クエリ・不正JSONは400 `invalid_request`。パスIDはデコード1回後に `manager/routes.py::validate_id(value)` と同じASCII英数字・`._-` の1〜64文字で検証し、`.` と `..` を拒否する。入力範囲違反は422 `validation_failed`。点検がDBの点検表と履歴の両方に存在しなければ404 `not_found`。認証切れは401、Origin・CSRF拒否は403で①の実装に合わせる。
- エラー本体は `{error:{code:string,message:string,request_id:string,fields?:Record<string,string>}}`。DBロックは503 `db_busy`、保存済みJSON・日時・状態の不整合は503 `data_invalid`、その他の例外は500 `internal_error`。503には `Retry-After: 1`。内部例外・ファイルパス・鍵をエラーに含めない。JSONとCSVに `Cache-Control: no-store`。
- `pc_api/server.py::PCAPI.dispatch(method,target)` の認証済み分岐から `pc_api/inspection_routes.py` を呼ぶ。DBは `ReadOnlyStorage._get_connection()` の `mode=ro`、`query_only`、待ち250msを使用し、新規接続を読み取り処理の最後に閉じる。1応答につき1接続・明示的な読み取りトランザクションを使い、`connection()` を持つ読み取りアダプターを既存関数に渡す。アダプターの `connection()` は同じ接続を貸し、内側でcommit・closeしない。通常の `Storage` の生成、DDL、書き込みは起動側の役割。受信フォルダーはランチャーから既存受信口の設定を渡す。
- 一覧の候補は最大10,000点検、選択点検・一覧集計に読む履歴は最大10,000行、1点検のmanifest写真は最大10,000件、進捗の機器は最大1,000行。各上限ちょうどは許可し、1件超過で422 `validation_failed`。SQLは必要な列と条件だけを選び、上限+1で検出する。上限超過を空・一部成功・正常と表示しない。画像検索ではルート、機器ID、ファイル名にかかわらず、保存済みの正規化済みSHA-256との照合だけで到着を確認する。

### 入出力

型名の `int` はJSON中の非負整数。日時はオフセット付きISO 8601文字列。欠損値を許す項目はキーを含めて `null` を返す。順序は第3節で固定する。

| メソッド・パス | 入力 | 成功応答 |
|---|---|---|
| GET `/inspections` | `filter=all\|action`（既定all）、`limit`、`cursor` | 200 `{items:InspectionListItem[],total:int,next_cursor:string|null,all_total:int,action_total:int}`。点検表と `inspection_options(readings)` の和集合。manifestだけの点検も含む。 `count` は該当点検のDB記録行数 |
| GET `/inspections/{id}/status` | パスIDのみ | 200 `{state:"受信中"\|"不足あり"\|"完了",matched:int,missing_photos:string[]}`。 `inspection_status(storage,id,incoming_dir)` の結果。配列の値はmanifestのファイル名 |
| GET `/inspections/{id}/progress` | パスIDのみ | 200 `InspectionProgress`。点検全体で1応答。 `status` も同じ読み取り結果から組み立てるため、画面は別リクエストの状態を合成しない |
| POST `/inspections/{id}/csv` | パスID、JSON `{device_name?:string,date_from?:string,date_to?:string}`。点検全体は `{}` | 200 添付ファイル。 `text/csv; charset=utf-8`、 `Content-Disposition: attachment`、ASCIIの `filename="inspection.csv"` とUTF-8で符号化した `filename*`。詳細は第4節 |

| 型 | 必須フィールド |
|---|---|
| `InspectionMeta` | `id,name:string`、`route_id,route_name,operator,place,started_at,completed_at:string|null` |
| `InspectionProgress` | `InspectionMeta` の全キー、`status`（上表のstatus型）、`devices:InspectionMeter[]` |
| `InspectionMeter` | `key:string`、`seq:int|null`（1始まり）、`off_route:boolean`、`device_id:string|null`、`name:string`、`unit:string|null`、`scale,tolerance:[number,number]|null`、`stage:0|1|2|4`、`value:number|null`、`read_status:"ok"|"low_confidence"|"failed"|null`、`sources:("phone_qr"|"manual"|"pc_qr")[]`、`photos:int`、`captured_at:string|null` |
| `InspectionListItem` | `InspectionMeta` の全キー、`count:int`、`status` の `state,matched`、`missing_photo_count:int`、`preview:InspectionMeter[]`、`summary:InspectionSummary` |
| `InspectionSummary` | `route_total,route_captured,route_recorded,captured,recorded,missing,off_route,off_route_recorded,warn,fail,wait,out_of_tolerance:int`、`all_ok,needs_action:boolean` |

### ページングとスナップショット

`limit` は既定50、整数1〜200。初回に一覧を完成させ、全件の `summary` と両タブの件数を算出してから絞り込み、ページを返す。並びは `started_at` の時刻降順（欠損は末尾）、同時刻は `id` のASCII降順。 `total` は選択タブ全体。 `preview` は進捗順で、ルートが取得できたときはルート上の先頭6件とルート外の先頭2件、その他は先頭6件。集計はプレビューに含まれない機器も対象にする。

一覧のDTOを生成時点から60秒、セッションあたり2件、サーバー全体で8件保持する。期限切れを先に除き、上限では作成が最も古いものを破棄する。失効の扱いは両上限で共通。セッション失効時はそのセッションの結果も破棄する。キャッシュの参照・追加・破棄はロックで保護する。カーソルは推測困難なサーバー生成値で、セッション、パス、`filter`、`limit`、次の開始位置に紐づける。再送は同じページを返し、末尾は `next_cursor:null`。不正形式は400、未知・期限切れ・破棄は410 `cursor_expired`、他セッションのカーソルは404、条件の変更は400。410で画面は古いページを捨て、同じタブの最初から1回だけ取得する。次ページの取得はユーザー操作で行う。

## 3. 点検進捗と画面

### サーバー側の組み立て

1. `pc_api/inspection_routes.py::list_inspections(storage,incoming_dir,session_id,query)` は `inspections` と点検IDのある記録を読み、`inspection_options(readings)` の件数を採用する。manifestの名称・開始日時を優先。履歴だけの場合は `id` 降順の先頭行の `inspection_name`（空なら点検ID）、開始は有効な撮影時刻（欠損なら受信時刻、次に `timestamp`）の最古、終了・担当・場所はnull。 `manager/web_data_ui.py::inspection_list` と同じ点検集合を対象にし、Streamlitはimportしない。
2. `get_inspection_status(storage,incoming_dir,inspection_id)` は存在確認後に `manager/routes.py::inspection_status(storage,inspection_id,incoming_dir)` を呼ぶ。 `get_inspection_progress(storage,incoming_dir,inspection_id)` は `get_manifest(storage,id)`、`get_route(storage,route_id)` を使う。ルートIDはmanifestの非空値を優先し、次にDB行の `id` 降順で最初の非空 `route_id`。ルートが削除済みならIDを保持、名称とseqはnull、全行を通常グループに出す。画面のルート集計・見出しはルートが取得できた場合だけ有効。ルートなしと削除済みはそれぞれ「なし」「ルート未取得」で表示を分ける。
3. 到着判定は `received_hashes(storage,incoming_dir)` を1応答で1回呼んで固定する。 `ReadOnlyStorage` 側のアダプターにはストレージと同じ `get_processed_hashes()` の読み取り契約を持たせる。 `inspection_status` と `arrived_manifest_devices(storage,manifest,readings,incoming_dir)` にキーワード専用引数 `hashes=None` を追加し、指定時は同じ集合を使う。Streamlitからの既存呼び出しでは今までどおり集合を取得する。manifestなしは `receiving`、manifestありで不足1枚以上は `short`、不足0は `complete`。sha256がnullのmanifest写真は既存関数どおり不足扱い。ファイル走査とDB読み取りの間に取り込みが進むことがあるため、次回更新で照合し直す。
4. `route_progress(route, [*readings,*arrived], manifest)` の結果をルート計画順と既知ルート外機器の候補に使う。実際の進捗は本節の写真照合で決める。ルート配置と写真の集合の和を取り、DB行とmanifest写真のsha256が一致すれば1枚とし、DB行の非空機器IDを優先する。重複したmanifestのsha256は先頭の写真名を機器集計用に使う。不足枚数はmanifestの行単位の既存仕様を維持する。sha256がない写真はファイル名、sha256がないDB行は整数の行IDで別々に数える。 `missing` 申告だけで実写を消さない。 `extra` 申告だけの機器はルート外の段階1（写真数0）として残す。
5. 機器IDがある写真はID単位、IDがなく名前がある写真は完全一致の名前単位、両方ない写真は上記の写真識別子単位。キーは `device:<id>`、`name:<name>`、`photo:<sha256|file_name|row_id>`（写真識別子には `hash:`、`file:`、`row:` を付ける）。最初にルート計画順、次にルート外（またはルートなし）をキー昇順。 `devices` から完全一致IDの `unit,min_value,max_value,tolerance_min,tolerance_max` を読む。表示名は機器DBの非空の名前、ルートの非空の名前、最新DB行の非空の名前、機器ID、「名前なし」の順。値と状態は記録行のうち `manager/export.py::_reading_time(row)` が最も新しい行（同時刻は行ID最大）を採用し、失敗した最新行も採用する。採用行の `captured_at` を優先し、なければ同じ写真と照合できたmanifestの撮影日時を使う。DB行がない場合は該当manifest写真の最大撮影日時。取得できなければnull。
6. `pc_api/inspection_progress.py::build_inspection_progress(storage,incoming_dir,inspection_id,readings,hashes)` は詳細と一覧から共用する。機器の段階は所属写真の最大値。写真のない計画行は0、写真のない追加申告行は1。機器の写真数は照合後の写真数で、申告だけの行は0。全DB行と写真を使って進捗を計算し、一覧は同モジュールの `summarize_progress(progress)` から第2節のサマリーを作る。一覧では1回の読み取りトランザクションと1集合を共有し、記録を先に点検IDでまとめる。DBで絞り込む前に全履歴を `readings()` で取らない。

### モックと実APIの対応

| `src/mock/inspections.ts` | 実APIと変換 |
|---|---|
| `Inspection.id/name` | `id/name` |
| `routeId/routeName` | `route_id/route_name`。削除済みIDは維持し、ルート有無のUI判定に `route_name !== null` を使う |
| `operator/place` | 同名。欠損時は「—」 |
| `startedAt/completedAt` | `started_at/completed_at`。画面は両方null可。日時はAsia/Tokyoで表示し、欠損は「—」 |
| `receive/missingPhotos` | 「受信中」→`receiving`、「不足あり」→`short`、「完了」→`complete`。詳細は `status.missing_photos.length`、一覧は `missing_photo_count` |
| `meters` | 詳細の `devices`。一覧は `preview` のみ描画し件数・判定は `summary` を使う |
| `MeterResult.seq/offRoute/id/name` | `seq` のnullをundefined、`off_route`→`offRoute`、`device_id` のnullを空文字、`name` はそのまま。Reactキーと詳細内リンクには `key` を追加して使用 |
| `unit/scale/tolerance` | 同名。単位が空ならnull。目盛りは有限値で最小<最大。許容範囲は有限値で下限≤上限。片端だけ・逆転・非有限値はnull |
| `stage` | 0=計画のみ、1=撮った申告あり／未着、2=ハッシュで到着確認／DB行なし、4=DB行あり。3は観測できないため返さない。DB行の存在は読み取り成功を保証しない |
| `value/status` | `value/read_status`。採用DB行がない場合は両方null。失敗行は値をnullにする。既存状態と値が矛盾し、値を確定できない行は `failed` 扱いとする |
| `sources` | `qr/sidecar_qr`→`phone_qr`、`manual/sidecar_manual`→`manual`、`pc_qr`→`pc_qr`。照合前のmanifestと照合後のDB行の出所を集め、列挙順で重複除去。null、`sidecar`、未知値は空扱い。`list` は実データで出さない |
| `photos/capturedAt` | `photos/captured_at` |

### React の接続

- `prototypes/react-records/` の `src/gauge/{Dial,GaugeHome,GaugeDetail,status}.tsx`、`src/gauge/{judge.ts,judge.test.ts,gauge.css}` を計器盤ブランチから取り込む。 `GaugeApp.tsx` は画面切替の参考とし、実接続用に同名ファイルを作る。 `src/mock/inspections.ts` と `src/mock/data.ts` は配信に含めない。テストが必要とするデータは `judge.test.ts` 内の入力として保持する。既存 shadcn 部品を使い、`Card/Badge/Button/ToggleGroup` の計器盤向けvariant・sizeと `index.css` のテーマ名は参照するものだけを両ブランチで照合して移植する。
- `src/api/types.ts` に第2節のDTOを追加。 `src/api/client.ts` に `getInspections(filter:"all"|"action",cursor:string|null,signal:AbortSignal)` と `getInspectionProgress(id:string,signal:AbortSignal)` を追加し、①の認証済みリクエストを使う。一覧の呼び出しは毎回 `limit=50`。 `src/gauge/model.ts` に画面用の `Inspection`・`MeterResult` 型と `toInspection(progress:InspectionProgress):Inspection`、`toMeter(row:InspectionMeter):MeterResult` を置き、対応表を適用する。各画面・判定・テストのモック参照をこの型と入力に差し替え、PR4単体で型検査が通るようにする。
- `src/App.tsx` の `tabFromHash(hash)` とナビに「点検」を追加。 `#gauge` は一覧、`#gauge/<encodeURIComponent(id)>` は詳細。初回直リンクと `hashchange` に対応。壊れたIDは「点検IDが不正です」と一覧リンクを表示。既存の記録・設定・機器登録のハッシュと session bootstrap を引き継ぐ。 `GaugeApp({inspectionId,onAuthExpired})` が取得状態を持ち、`GaugeHome({items,filter,totalAll,totalAction,onFilterChange,onNext,canNext})` と `GaugeDetail({ins})` を描画する。詳細の「要確認を上に」は既存の並べ替えを保つ。
- 初回・タブ切替で読み込み表示→成功なら一覧または空表示、詳細404なら「点検が見つかりません」。手動「更新」は初回ページ／同じ詳細IDを再取得し、同じ画面の更新失敗時は既存データと更新エラーを残す。「再試行」は同じ取得先。自動更新を有効にした詳細は5秒ごとに再取得し、直前の通信中は次を起動しない。未選択・別画面・非表示タブでは自動更新しない。切替・アンマウント時に通信を中断し、古い応答で状態を上書きしない。401は既存の失効画面へ移る。空の一覧・詳細を完了とは表示しない。
- `judge.ts::judge(m)` の既存優先順を維持する。段階0、失敗、未完了を先に判定。段階4の有限の値を下限・上限と比較し、両端は範囲内。許容範囲外は `outOfTolerance=true`、読み取り結果の分類と記録台数は維持する。許容範囲nullは「許容範囲 未設定」と中立の二重丸、緑帯なし。許容範囲の欠損だけで要対処にはしない。目盛り範囲外と低信頼は既存の要確認を維持する。名前だけの記録は「機器IDなし」とし、名前なしとは区別して要確認にする。
- `summarize(ins)` とサーバーの `summarize_progress` は同じ条件を使う。撮影≥到着≥読み取れた≥記録を保ち、記録は段階4・有限の値あり・失敗以外。 `needs_action` は未撮影、ルート外、要確認、失敗、許容範囲外、不足写真のいずれか。 `all_ok` は受信完了、機器1件以上、対処なし、全機器が `ok` の組み合わせ。 `ReceiveBadge` は不足と受信中を点検完了にしない。両実装で同じ境界ケースを試験する。
- 配色、罫線、表示密度、状態の図形は合意済み `DESIGN.md` を守る。アニメーション、針の補間、数値のカウントアップ、画面遷移演出は使わない。詳細カードへの移動は `scrollIntoView({behavior:"auto",block:"center"})` とフォーカス移動。色に加えて既存の文字と図形で状態を示す。

## 4. 正式CSV

実装入口は `pc_api/inspection_csv.py::export_inspection_download(storage,inspection_id,filters)`。 `filters` の機器名は256文字以内の完全一致、日付は `YYYY-MM-DD` の実在する日付、両端を含む。逆転は422。空の機器名と「すべて」は送信しない。点検IDはURLで固定。未知・重複キーと非オブジェクトは400、ボディ最大4,096バイトで超過413。

1. 点検の存在を検証し、選択点検の履歴を取得。 `manager/export.py::filter_readings(readings,device_name,date_from,date_to,inspection_id)` → `latest_per_device(filtered)` の順。日付境界と日時の優先順位は既存関数を使う。最新の採用単位は既存の機器名で、名前なしの行は各1件。失敗→要確認→正常、同状態内は日時と行ID降順。計器盤の機器ID単位の採用・許容範囲はCSVに混ぜない。
2. サーバー内部の `TemporaryDirectory` 内で `export_inspection_csv(latest_rows,out_dir=temporary_dir)` を呼ぶ。戻り値のファイルからバイト列とベース名を読み、エラー時も一時領域を片付ける。列順は「メーター名称、読み取り値、状態、取込時刻、画像参照」。UTF-8 BOM、CRLF、CSVの引用符、数式対策の先頭アポストロフィ、空欄、画像参照を生成関数のまま保つ。既知点検で該当記録0件はヘッダーのみ。上限超過はCSVを作らず422。
3. `src/api/client.ts::downloadInspectionCsv(id,filters,signal)` は①の認証・CSRF付きPOSTを使い、 `{blob:Blob,name:string}` を返す。 `filename*` のUTF-8値を読めなければ `inspection.csv`。 `src/lib/download.ts` の `download(name,text,type)` を `text:string|Blob` に広げ、Blobのバイト列をそのまま保存する。既存の文字列ダウンロードを引き継ぐ。詳細の `GaugeDetail({ins,onExport,exporting,exportError})` に「点検の結果を書き出す」を置き、この画面では `{}` を送る。記録画面から同一条件の出力が必要なら既存の選択点検と日付・機器名を渡す。送信中はボタン無効、失敗時はその場にエラー、401は既存の失効表示。自動再送は行わない。
4. `manager/inspection.py` の `create_inspection(storage,inspection_id,date_from,date_to,device_ids,now=None)`、`restore_inspection(storage,manifest)`、`export_inspection(inspection,output_dir)` は期間・機器指定の点検帳票の入口。②の5列CSVからの呼び出しは0回。これらが生成するファイルを5列CSVの代用にしない。

## 5. PR単位の作業

各PRはテストを含む手書き差分おおむね300行以内。合意済みファイルの取り込みと生成バンドルは別集計とし、取り込み元と生成元を照合する。表の `src/` は `prototypes/react-records/src/` 基準。節ごとに同じPRで上限を超える場合は、表の責務境界で先に土台をマージしてから利用側を接続する。

| PR | 依存 | 触るファイル | 受入条件 |
|---|---|---|---|
| 1 読み取りと受信状態 | ① PR3 | `pc_api/{server,launcher,inspection_routes}.py`、`manager/routes.py`、`tests/test_pc_inspection_status.py` | 実受信フォルダーが渡る。manifestのみ、履歴のみ、未着、到着、欠損ハッシュ、未知ID、401、DB busyを確認。既存スマホ応答とStreamlitの受信状態に回帰なし |
| 2 写真・機器ごとの進捗 | PR1、① PR4、過去ルート・出所・中間工程の方針確認 | `pc_api/inspection_progress.py`、`pc_api/inspection_routes.py`、`tests/test_pc_inspection_progress.py` | ルート順、未撮影・未着・到着・記録、同一写真の重複排除、失敗行、名前なし、両端を含む許容範囲と未登録、上限を確認 |
| 3 一覧とページング | PR2 | `pc_api/{inspection_routes,inspection_progress,inspection_pages}.py`、`tests/test_pc_inspection_pages.py` | manifestのみと履歴のみが一覧に出る。プレビュー外の要対処も件数に反映。更新中のページ欠落・重複0、limitの0・1・50・200・201、条件変更・別セッション・60秒失効を確認 |
| 4 計器盤資産とモデル | ① PR1、実APIの型確定 | `src/api/types.ts`、`src/gauge/{Dial,GaugeHome,GaugeDetail,status}.tsx`、`src/gauge/{judge.ts,judge.test.ts,gauge.css,model.ts}`、`src/index.css`、`src/components/ui/{card,badge,button,toggle-group,toggle}.tsx` の必要箇所 | 既存の配色・フォーカス・図形を保持。未設定・上下端・1点の許容範囲・範囲外・空点検・受信不足の判定を確認 |
| 5 点検の画面接続 | PR3・4、① PR6 | `src/App.tsx`、`src/api/client.ts`、`src/gauge/{GaugeApp,GaugeHome,GaugeDetail}.tsx` | 一覧と詳細を実APIから開ける。直リンク、戻る、ページ続き、対処タブ、空・404・410・401、更新中の画面切替を確認。既存の3画面へ戻れ、計器盤の判定とサーバー集計が一致 |
| 6 正式CSV API | PR1、CSVの受け取り方と帳票の範囲の決定 | `pc_api/{server,inspection_routes,inspection_csv}.py`、`tests/test_pc_inspection_csv.py`、`tasks/design/React移行-API設計.md` | 同一入力を通したStreamlitの5列CSVとバイト一致。複数写真、同時刻、名前なし、失敗、当日日付境界、0件、10,000件と超過、CSRF拒否、同時出力と一時ファイル掃除を確認 |
| 7 CSV操作と配信 | PR5・6、① PR8 | `src/api/client.ts`、`src/gauge/{GaugeApp,GaugeDetail}.tsx`、`src/lib/download.ts`、`pc_api/static/`、`tools/verify_react_migration.py` | ランチャー起動→セッション交換→点検一覧→詳細→CSV保存。失効と再起動、Nodeなしでの同梱配信、既存の記録・設定・機器登録・PDF出力を確認 |

PR1の時点で現行の受信と既存画面が動くこと。配信PRでは `dist/` の `index.html` と参照先の生成物を `pc_api/static/` に反映し、旧ハッシュの生成物を除く。

各PRでリポジトリルートから `python -m unittest discover -s tests -q` を実行する。Reactの差分があるPRは `cd prototypes/react-records; npm test; npm run lint; npm run build` の各終了コードを確認する。配信PRはリポジトリルートに戻り `python tools/verify_react_migration.py` を実行する。

受入では、同じDBと受信フォルダーでStreamlitとReactを比較する。manifest受信前、写真1枚不足、取り込み後の揃った状態、ルート外1台、撮り忘れ1台、読み取り失敗、許容範囲未設定と範囲外を確認する。受信の「完了」と作業の「点検 完了」を区別し、5列CSVは上記の同じ絞り込みで照合する。
