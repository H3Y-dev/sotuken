# React本移行 点検詳細の写真表示

## 目的

2026-11-20の決定に基づき、点検詳細の機器カードから、そのカードの判定に使った記録の元画像と検出結果オーバーレイを確認できるようにする。既存の計器盤の方向性Aに沿って、機器カード末尾の「写真」から記録タブと共通のダイアログを開く。

## 採用案と代案

機器行に `image_id` と `overlay_image_id` を追加する。どちらも既存の画像APIで使えるIDで、画像はボタン押下時に取得する。カードと同じDB行を参照でき、点検用に `Reading` を作ったり、記録詳細を再取得したりする必要がない。

代案は `reading_id` と画像有無のフラグを返し、押下後に `fetchReading` でダイアログ用のデータをそろえる方法。既存の記録ヘッダーをそのまま表示できる一方、画像の取得前に追加の通信と、その待機・失敗処理が生じる。画像の参照に必要な情報は既存の署名付きIDで表せるため、採用しない。

## APIとPythonの実装済み契約

以下は実装済みの仕様。React担当は Python の実装を変更せず、一覧の応答テストだけを追加する。

| 変更ファイル | 変更内容 |
| --- | --- |
| `pc_api/inspection_routes.py` | `_PROGRESS_READING_COLUMNS` の末尾に `image_path` と `overlay_path` を追加する。詳細と一覧のSQLはこの列定義を共用する。 |
| 同上 | `get_inspection_progress(storage, incoming_dir, inspection_id, *, image_id)` と `list_inspections(storage, incoming_dir, session_id, query, *, image_id, page_cache=None)` に必須キーワード引数を追加する。認証済みの `dispatch_inspection` から両方に `image_id=api.image_id` を渡す。statusハンドラーには渡さない。カーソルの後続ページは既存スナップショットを返す。 |
| `pc_api/inspection_progress.py` | `build_inspection_progress(storage, incoming_dir, inspection_id, readings, hashes, *, image_id)` に同じ必須引数を追加する。型契約は「`.id` 属性を持つ行オブジェクトと種別 `'original' \|'overlay'` を受け取り `str` を返す関数」。呼び出し元は上記2関数。 |
| 同上 | 関数内の `_build_meter(grp, seq, off_route)` の戻り値に2キーを追加する。既存の `latest_row` を使う。行があり、その種別のパスに値があれば `image_id(latest_row, 'original')` または `image_id(latest_row, 'overlay')` を呼ぶ。行なし、パスがNULLまたは空文字ならその種別は `None`。パスは既存の真偽値判定を使い、空白だけのパスは想定しない。同時刻なら行IDが最大の行を使う。失敗行も選択対象で、古い記録の画像にはさかのぼらない。 |

両キーとも必須で、型は `string | null`。点検詳細の `GET /api/v1/inspections/{id}/progress` の `devices[]` と、一覧の `GET /api/v1/inspections` の `items[].preview[]` に同じ形で入れる。機器行の契約を一覧と詳細で同形に保つため、一覧も既存の件数制限と順序で共通の機器行を返す。ボタンは詳細だけに設ける。

以下は写真関連のキーだけを抜き出したJSON例。署名部分は説明用で、実際には起動中のAPIが発行した値を使う。

```json
{"devices":[{"key":"device:DMO-001","image_id":"42-o-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","overlay_image_id":null},{"key":"device:DMO-002","image_id":null,"overlay_image_id":null}]}
```

```json
{"items":[{"id":"demo-01","preview":[{"key":"device:DMO-001","image_id":"42-o-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","overlay_image_id":null},{"key":"device:DMO-002","image_id":null,"overlay_image_id":null}]}]}
```

DBパスの有無でIDを発行し、この段階では画像ファイルを開かない。画像IDは `PCAPI.image_id` だけが発行する。パスはSQLで取得した行の内部に留め、絶対パス・相対パスともに応答へ含めない。クライアントはIDを分解せず、認証済みの既存 `fetchImageBlobUrl` → `GET /api/v1/images/{image_id}` を使う。HMAC、許可ルート、ファイル形式の検証は画像配信時の既存処理に任せる。

## Reactの変更

以下のパスは `prototypes/react-records/src/` からの相対パス。

| 変更ファイル | 型・関数 |
| --- | --- |
| `api/types.ts` | `InspectionMeter` に必須の `image_id: string \| null` と `overlay_image_id: string \| null` を追加する。 |
| `gauge/model.ts` | `MeterResult` に必須の `imageId: string \| null` と `overlayImageId: string \| null` を追加する。`toMeter(row: InspectionMeter): MeterResult` で各項目を `row.image_id ?? null`、`row.overlay_image_id ?? null` に変換する。旧応答でキーが省略された場合も各値は `null` になる。 |
| `components/OverlayPreview.tsx` | 写真用の `PreviewPhoto` 型を公開する。型は `{ name: string; deviceId: string \| null; imageId: string \| null; overlayImageId: string \| null }`。`OverlayPreview(props)` の引数型は `{ reading: Reading; onClose: () => void; photo?: never }` と `{ photo: PreviewPhoto; onClose: () => void; reading?: never }` の共用体。 |
| `gauge/GaugeDetail.tsx` | `MeterCard` の既存propsに `onPhoto: (meter: MeterResult, trigger: HTMLButtonElement) => void` を追加する。`GaugeDetail` は両方のカード列に同じハンドラーを渡す。選択状態 `selected: { photo: PreviewPhoto; trigger: HTMLButtonElement } \| null` の初期値は `null`。 |
| `App.tsx` | `switchTab` でハッシュを変更する分岐と、`onHash` で `nextHash !== hash` が確定した直後に `setSelected(null)` を追加する。記録側の選択を破棄し、点検側と `id="preview-dialog-title"` が重複しないようにする。点検詳細のアンマウントは `onHash` 内の既存の `setInspection(null)` に任せる。`GaugeDetail` の呼び出しは既存のpropsを使う。 |

### 機器カードと選択状態

カード末尾に既存の `Button` を `type="button"`、`variant="outline"`、`size="field"`、`className="self-start"` で置き、表示文言は「写真」とする。両画像IDが `null` のカードにはボタンを描画しない。表示名は `lib/records.ts` の `displayNameOf({ device_name: m.name })` で求める。機器IDが空なら `null` として扱う。

- `m.seq !== undefined` なら `aria-label` は「No.<seq> <機器名>の写真」。`m.seq === undefined` の行は「ルート外<n> <機器名>の写真」。`<n>` は、カードの並び順で `m.seq === undefined` の行だけを数えた1始まりの連番で、常に付ける（衝突時だけ付けるような分岐は作らない）。後者にはルート未取得の非計画行も含む。
- 機器IDがあれば機器名の直後に全角括弧で「（<機器ID>）」を付ける。例は「No.1 圧力計A（DMO-001）の写真」「ルート外1 名前なし（DMO-002）の写真」「ルート外2 名前なしの写真」。これで、機器IDも名前もない非計画行が複数あっても、ラベルは必ず一意になる（2026-11-20メインが決定）。
- クリック時に `onPhoto(m, event.currentTarget)` を呼ぶ。ハンドラーはその場で `photo` を作成し、`{ photo, trigger }` を `selected` に保存する。`photo` には `m.name`、`m.id || null`、`m.imageId`、`m.overlayImageId` を入れる。以後、ポーリングや手動更新で機器行が置き換わっても `selected.photo` は作り直さない。`selected` がある間だけ `OverlayPreview` を1つマウントする。

| 機器の状態 | 表示 |
| --- | --- |
| 未撮影、または manifest だけで DB 行がない（受信済みを含む） | ボタンなし |
| 読み取り成功で両IDあり | ボタンあり。両枠に対象画像を表示する。 |
| 読み取り成功で元画像IDあり、オーバーレイIDなし | ボタンあり。元画像と「オーバーレイ画像はありません。」を表示する。 |
| 読み取り失敗で元画像IDのみあり | ボタンあり。元画像と「オーバーレイ画像はありません。」を表示する。 |
| 成否を問わず両IDなし | ボタンなし |
| 元画像IDなし、オーバーレイIDあり | ボタンあり。「元の写真が見つかりません。」とオーバーレイを表示する。 |
| ルート外、機器IDなし、ルート未取得 | 同じ画像IDの条件でボタンと各枠を表示する。 |
| 画像取得が404 | 該当する枠に上記の欠落文言を出し、取得できた側を表示する。その他の取得失敗には既存のエラー文言を使う。 |

### ダイアログのヘッダーと画像取得

`props` は分割代入せず、`props.photo` と `props.reading` で分岐する。`detail` は `useState<Reading | null>(props.reading ?? null)` で初期化する。`detail` がある記録モードだけ、`StatusBadge`、記録#、日時、値、確からしさ、失敗段階、`data-preview-reading-id`、`detailError` を既存の条件と表示形式で描画する。

写真モードの見出しには `displayNameOf({ device_name: props.photo.name })` の結果を使う。空白だけの名前と「名前なし」の判定を記録モードと共有する。機器IDがあれば「機器ID: <機器ID>」を表示し、見出しの下に「この機器の最新の記録の写真」を1行で添える。カードの「写真 N枚」は機器の写真総数を表し、ダイアログが表示する対象は最新の記録1件。各画像の `alt` は見出しと同じ機器名を使い、「〈機器名〉 の検出結果オーバーレイ」「〈機器名〉 の元画像」とする。

- effectの外で `readingId = props.reading?.id ?? null`、`photoImageId = props.photo?.imageId ?? null`、`photoOverlayImageId = props.photo?.overlayImageId ?? null` を求める。画像取得effectの依存配列はこの3値。写真モードでは先頭が常に `null`、記録モードでは後ろの2値が常に `null`。`props`、`photo`、`reading`、`detail` のオブジェクト参照を依存配列に入れない。
- 記録一覧の行は `useRef<Reading | null>(props.reading ?? null)` で保持する。画像取得effectより先に置く同期用のeffectで、`props.reading` が変わったときにrefを更新する。`readingId !== null` のときだけrefから現在の記録を取得して `detail` の初期表示に使い、`fetchReading(readingId, controller.signal)` を呼ぶ。成功した行で `detail` と取得対象の2つのIDを更新する。中断以外の失敗時は既存の `describeApiError` で `detailError` を設定し、保持した記録のIDへフォールバックする。写真モードでは上記の2つの写真IDをそのまま画像取得に使う。`original` と `overlay` の初期状態も、それぞれのモードの初期IDの有無で既存の `emptySlot` を使って設定する。
- 同じ `AbortController` を詳細と画像の取得で共用する。既存の2枠の並列取得、欠落・取得エラー表示、モード切替を使う。閉じるか画面から離れた際は既存のcleanupで取得を中断し、作成済みのBlob URLをすべて解放する。閉じて開き直すと表示切替は「並べて表示」に戻る。カードとダイアログにアニメーションを付けない。

### DOM上の配置とフォーカス

`OverlayPreview` の既存のダイアログ全体を `createPortal`（`react-dom`）で `document.body` に描画する。点検画面のライブ領域は `App.tsx` の `section.gauge[aria-live="polite"]` にある。実際の `lib/fakeDom.test-support.ts` と導入済みのReact DOMを使った検査で、ライブ領域内からbody直下へのマウント、`activeElement` の更新、クリック伝播、アンマウント時の削除を3回確認した。bodyに描画すればダイアログはこのライブ領域の外に置かれる。

共通の「閉じる」ボタンに `useRef<HTMLButtonElement>(null)` を渡し、写真モードのみマウント時のeffectで `closeButtonRef.current?.focus()` を呼ぶ。記録モードは従来どおりフォーカスを動かさない。閉じるボタン、Escape、背景クリックは既存の `onClose` へ流す。点検側の `onClose` は `selected` から `trigger` を取り出して `selected` を `null` にし、`document.contains(trigger)` が真のときだけ `trigger.focus()` を呼ぶ。記録側は既存の閉じる処理を使う。

## テストと受入

### Python

既存の `tests/test_pc_inspection_progress.py` は、同時刻の行IDが最大の失敗行からのID発行、元画像だけある場合、署名形式と記録APIとの一致、保存パスの除外、対象画像がない場合の明示的nullを確認する。`tests/test_pc_inspection_pages.py` は、一覧previewと詳細の両IDの一致を確認する。

React担当は `tests/test_pc_inspection_pages.py` に、一覧previewで保存パスを返さないテストを1件追加する。画像パスとオーバーレイパスに別々の既知の文字列を持つ記録を作り、その機器が `items[0]["preview"]` に含まれることを確かめる。各preview機器行で `image_path` と `overlay_path` の両キーが存在せず、シリアライズした各行に二つのフィクスチャの保存パス文字列が含まれないことを確認する。Pythonの実装は変更しない。

### React

- `gauge/model.test.ts` に変換テストを1件追加する。IDあり、両キーが明示的null、旧応答で両キーを物理的に省略した行を同じテストで変換する。旧応答だけを `as unknown as InspectionMeter` でキャストする。
- `gauge/judge.test.ts` の型付き固定機器行 `MeterResult` に `imageId: null, overlayImageId: null` を追加する。`App.test.tsx` の `progress()` と `page()` の機器行には `image_id: null, overlay_image_id: null` を追加する。
- `App.test.tsx` の `vi.mock("@/api/client")` に `fetchImageBlobUrl` と `fetchReading` の `vi.fn()` を追加する。`beforeEach` の `vi.resetAllMocks()` の後、各テストで使用するモックの実装を設定する。画像成功時は `{ url, revoke: vi.fn() }`、404相当では `null` を返す。GET件数は `toHaveBeenCalledTimes` で数え、`mock.calls` の第1引数で対象IDを照合する。
- 写真ボタンの検索ヘルパーを `App.test.tsx` に追加する。カード側は既存の `container` で `[aria-label="…"]` を使って検索し、対象ありの検査では一致要素が1つであることを確かめる。ポータル側は `doc.body` から `[role="dialog"]` を検索し、そのダイアログ内で `img`、`button`、テキストを調べる。Escapeは既存のwindowイベント転送先である `doc` に `FakeEvent("keydown", { key: "Escape" })` を送る。フォーカスは `doc.activeElement` で検査する。

| 画面テスト | 操作と確認 |
| --- | --- |
| 1. ボタン表示 | 未撮影、manifestのみ、両IDなしの失敗ではボタンなし。元画像のみの失敗、オーバーレイのみのルート外、両方ある正常では指定したラベルのボタンが1つずつある。 |
| 2. 写真を開く | 初期表示では画像取得0回。両IDのある機器を開くと画像取得2回でIDが一致し、`fetchReading` は0回。両画像の `src` と `alt`、機器名、機器ID、最新の記録である旨の補足が出る。`[data-preview-reading-id]` は存在しない。直後のフォーカスは「閉じる」。Escapeで消え、押した写真ボタンへ戻る。別機器を開いた後はその機器の画像だけが出る。 |
| 3. 片方が404 | 元画像IDに対して `fetchImageBlobUrl` が `null`、オーバーレイIDに対してBlob URLを返す。元画像の欠落文言とオーバーレイが同時に出る。 |
| 4. 表示中の更新 | 画像IDが変わる次の応答を `fetchInspection` に返させる。ダイアログを開いて画像が表示されたら、Vitestでfake timersを有効にし、Fake DOMの `win.setTimeout` と `win.clearTimeout` に現在のグローバル関数を設定する。「自動更新」のチェックボックスをオンにしてから `act` 内で `vi.advanceTimersByTimeAsync(5000)` を実行する。続けて「更新」を押し、さらに異なるIDの応答を返す。各更新で進捗の取得が実行され、画像取得回数とID、ダイアログの存在、表示中の各 `img` の `src` が変わらないことを確かめる。テスト終了時にタイマーを実時間へ戻し、`win` の元の関数を復元する。 |
| 5. 解放 | 画像の取得成功後に「閉じる」を押し、対象画像ごとに保持した `revoke` モックが1回ずつ呼ばれることを確認する。 |
| 6. 記録タブの回帰 | 記録を直接渡して表示し、`fetchReading` が対象IDで呼ばれ、記録#、日時、`StatusBadge` のラベル、`data-preview-reading-id` が表示されることを確かめる。フォーカスは動かず、Escapeで閉じることを確かめる。 |

### 実行コマンドとEdgeの受入

1. リポジトリルートから `C:\卒研\git_stk\sotuken\venv\Scripts\python.exe -m unittest tests.test_pc_inspection_progress tests.test_pc_inspection_pages tests.test_pc_inspection_status tests.test_pc_inspection_csv tests.test_pc_api_server` を実行する。全体は同じ Python で `python -m unittest discover -s tests` を実行する。
2. `prototypes/react-records` で `npm test`、`npm run lint`、`npm run build` を実行する。テストとビルドをすべて通し、oxlintの警告を既存の7件から増やさない。
3. `pc_api` 経由でEdgeを開く前に、同ディレクトリで `npm run build:static` を実行する。`pc_api/static` が更新され、旧ハッシュのファイルが残っていないことを確かめる。
4. 本番DBと分けた試験DBで、両画像付きの正常機器、元画像だけある失敗機器、写真のあるルート外機器、未撮影機器を含む点検を選ぶ。一覧と詳細の初期表示で画像GETが0件、ボタンを押すと対象画像のGETだけが走ることを開発者ツールで確認する。機器名と対象画像を照合する。
5. 写真モードでは開いた直後に「閉じる」にフォーカスがあり、Tabで表示切替へ進めることを確認する。記録モードではフォーカスを動かさないことを確認する。自動更新を有効にし、進捗の5秒ポーリングを1回以上またいでもダイアログが残り、画像が差し替わらないことを確認する。Escapeで閉じると押したボタンに戻り、別機器を開くと対象機器の画像だけが出ることを確認する。
6. 試験用画像の片方を別名へ一時移動する。再度開き、欠落文言と取得できた側の画像が同時に出ることを確かめてファイル名を戻す。記録タブから同じ写真を開き、従来の画像と記録情報が表示されることを確認する。

## 実装順と既存設計書への反映

1. React担当が、上記のReact実装とテスト、一覧のPython応答テストを追加し、実行コマンドとEdgeの受入を確認する。
2. 文書担当が `tasks/design/React移行-API設計.md` の第3節の `GET /inspections` と `GET /inspections/{id}/progress` に2キーと既存画像APIの参照を追記する。第4節の `image_id` に、点検詳細と一覧previewが同じ発行規則を使うことを追記する。`tasks/design/React本移行-点検確認と計器盤.md` の利用API、第2節の機器行・preview契約、項目6の進捗ビルダー引数、点検詳細のカード、受入手順をこの設計に合わせる。

## 範囲外

複数枚の写真履歴、フォーカストラップ、API再起動前の署名IDが401になった場合の専用案内（既存の取得エラー文言を使う）、DB記録前の写真配信、古い記録への画像フォールバック、サムネイル、画像アップロード、新規API、DBスキーマ変更、CSVの画像参照変更、StreamlitとAndroidの変更。

## 未確定事項

- なし。機器IDも名前もない写真は `pc_api/inspection_progress.py` で `photo:<photo_id>` ごとに別の機器行になるが、ルート外の `aria-label` はカードの並び順の連番を常に付けるため一意になる（上の「ボタン」の節。2026-11-20決定）。
