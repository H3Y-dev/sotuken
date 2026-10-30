# PCインストーラー化

DBを正本にして、点検の終了時に名称・読み取り結果・時刻の表を保存する。  
表はドキュメント、画像・ログ・DBはLocalAppDataへ分ける。  
Python・Ollama・モデルを同梱する設計とし、実装は11/5の通し確認後に進める。

ユーザーに確認したいこと：容量上限を超える場合、Setup.exeと同梱データを一つのZIPで渡す形でよいか。USBは任意機能とする案でよいか。

調査日：2026-10-30。コード確認時のHEAD：`51eaffe`。以下は推奨設計であり、実装済みではない。

## 改訂（2026-10-30 Argonレビュー反映。ユーザー承認済み。**この節が下の本文より優先**）

2人体制（大久保とClaude）で作れる初版に絞る。レビュー全文は `PCインストーラー化-レビュー(Argon).md`。

| 項目 | 改訂内容（下の本文との差分） |
|---|---|
| 表の行の単位（ユーザー決定） | 点検の終了で書き出す表は**メーター別の採用値（1台1行、原則最新の1件）**。全履歴の出力（1画像1行）は別機能として残す。記録タブ（`記録タブ-DESIGN.md`）の「メーター別の最新値」と同じ集計を共有する |
| 点検のテーブル | `inspections` / `inspection_items` / `inspection_exports`、行データの固定、`r001`連番、SHA-256復旧は**初版では作らない**。終了操作は「選んだ期間・絞り込みの採用値を、`点検_日時.csv`（一時ファイルへ書いてから改名）に出す」だけ。同名があれば連番を付けて上書きしない |
| 旧データ移行 | `migrate.py`・`user_version`・backup退避・パス変換は**作らない**（引き継ぐ旧本番DBがない）。列の追加は `manager/storage.py` の既存方式（`ALTER TABLE ADD COLUMN`）だけ |
| 表の列（初版） | メーター名称・読み取り値・撮影時刻・取込時刻・状態（`status`）・画像参照。**単位の手入力・読み取り範囲・点検ID・出力版・`legacy:<id>`は初版では出さない**（単位はQRの`unit`で将来対応） |
| 配布方式 | PyInstaller一本にせず、**埋め込みPython（またはvenvの同梱）をInno Setupで固め、ランチャーから同梱`python.exe`を呼ぶ方式を第一候補**にする。PyInstallerでのStreamlit・RapidOCRの梱包は難所なので、**先に試作して決める**（T0） |
| VLM | GPUなしのPCでは数分かかるため、**試行推論が遅い環境では自動でVLMを無効化し、OCRのみ**にする |
| 配布物 | `Setup.exe`と`models/`を分けた1つのZIP。不要なblob（約3.3GB）を除く（確認事項1：承認） |
| USB吸い出し | **任意機能**（確認事項2：承認）。Wi-Fi送信を主経路とする |
| 署名 | 有料の署名は取らない。`SETUP.md`にSmartScreen通過の手順を載せる。`THIRD_PARTY_NOTICES.txt`はT11で作る |

**追加する先行タスク**
- **P-05（委任済み）**: `watch_inbox`が起動のたびに`incoming/`の全画像を再推論する問題の修正（1枚約22秒×枚数）。インストーラー化の前提。
- **T0（試作）**: 埋め込みPythonとPyInstallerの両方で、Streamlit＋RapidOCRが動く最小構成をクリーンなWindowsで試し、梱包方式を決める。
- 対象漏れの補正（Argon指摘）: T3bに`app.py`の相対パス（`temp_`等）、T4に`manager/overlay.py`（`os.path.relpath`）、T10に`vlm_scale_value.py`（`ollama`の接続先）を加える。

**改訂後のタスク順（8本）**: T0試作 → T1「採用値のCSV書き出し」（`manager/export.py`、`app.py`、テスト。表の列は上のとおり）→ T2+T5最小（保存先の集約と`captured_at`・`received_at`の列追加）→ T3a/T3b（受信・USB・監視・画面の保存先）→ T4（画像・ログの保存先、`overlay.py`）→ T10（起動管理）→ T11（配布物）→ T12（インストーラー）。T8b・T9は削除。

## 1. 主データの表

推奨案は1画像につき1行。同じ画像を再処理した場合は選択した記録を出し、別に撮った同じメーターの画像は残す。理由は撮り直しや失敗を隠さず確認できるため。メーターごとに最新1件だけにする別案は、途中の異常を落とすので初版では採らない。

| 優先順・列 | DBとの対応・取得するコード | 推奨する扱い・理由 |
|---|---|---|
| 必須：メーター名称 | `meter_readings.device_name`。 `manager/ingest.py:device_name_from_sidecar` | `unknown`・空白は「名称未設定」、要確認。終了前に利用者がDB上で直せるようにする |
| 必須：読み取り結果 | `meter_readings.value`。 `manager/storage.py:save_reading` | 自動値。失敗は空欄で、0にしない。現場入力値へ勝手に置換しない |
| 必須：撮影時刻・取込時刻・処理後保存時刻 | 現状は`timestamp`のみ。 `save_reading`の`datetime.now()`は処理後保存時刻。撮影時刻は`manager/sidecar.py:SidecarMetadata.captured_at`にあるが`ingest_result`は保存しない | DBへ`captured_at`・`received_at`を追加。取込時刻はHTTP/USBのファイル受け入れ完了時。新規はUTC保存・表ではオフセット付きJST。旧`timestamp`は旧PCのローカル時刻として原文を残し、未知の撮影・取込時刻は空欄 |
| 追加1：判定・要確認理由 | `status`・`failure_code`・`failure_detail`。 `manager/record.py:judge_status` | `ok`=正常、`low_confidence`=要確認、`failed`=失敗。状態不明・名称未設定も要確認。装置の正常・異常判定とは区別する |
| 追加2：単位 | DB・サイドカーとも保存項目なし。`manager/record.py:Reading.unit`は型定義だけ | nullableの`unit`列を追加し、人が確認して入力。推測しない。未入力は「単位未設定」と確認画面に出す |
| 追加3：現場入力値・入力区分 | `image_truths.operator_value`を`image_sha256`で結合。`input_method`は`judge_input_method` | 自動値と併記。`auto/manual/corrected`は出所を表す。現場入力があっても自動判定を正常へ変えない |
| 追加4：読み取り範囲の下限・上限 | `raw_data_json.min_value/max_value`。`meter_pipeline.py:read_meter`→`ingest_result` | 推定した目盛範囲。警報閾値や、人が入力した`image_truths.scale_min/scale_max`と混ぜない。出力対象分だけJSONを読む |
| 追加5：画像参照・記録ID | `image_path`・`reading_id`。`manager/image_store.py`・`Storage` | 旧記録でreading_idが欠ける場合は`legacy:<id>`。画像参照は同じPCで探すためのパス。表だけ渡しても画像は付属しない |
| 追加6：点検ID・出力版・処理版 | 点検・出力版は新設。`pipeline_version`は通常取込で未設定、`manager/reprocess.py`では設定 | ビルド時の処理版を今後保存。旧値は空欄。信頼度数値`confidence`も通常処理では埋まらず、確率に見えるため初版の表には出さない |

現行`manager/export.py:export_to_csv`はUTF-8 BOM対応済み。ただし`timestamp`を`captured_at`として出す別名処理は修正が必要。`app.py`は絞り込み表示にかかわらず`history`全件を書き出すため、対象IDの明示が必要になる。

## 2. 「点検」の定義と書き出し

推奨案は「利用者が選んだ取込済み記録の集合」。開始時に点検IDを作り、期間・名称で絞って対象を選ぶ。期間だけで自動確定する別案では遅れて届く画像が紛れるため、期間は選択の補助に使う。予定メーター一覧による未撮影検出は後回しにする。

| 操作・保存 | 推奨する仕様 |
|---|---|
| 開始・選択 | `inspections(id, started_at, ended_at, state)`と`inspection_items(inspection_id, meter_reading_id)`を追加。後者は既存の整数主キー`meter_readings.id`を参照し、組を一意にする。点検IDはDBで管理し、`meter_readings`へ点検列は足さない。開始・選択をDBに保存して再起動後も復元 |
| 対象の固定 | 同じ`image_sha256`の候補は最新の`id`を既定にし、確認した行の`id`を固定。ハッシュなしは別記録として残す。再処理・後着画像を既存の点検へ自動追加しない |
| 終了前の確認 | 対象件数、失敗・低信頼度・名称未設定・単位未設定の件数と該当行を表示。PCで処理待ち・処理中の画像があれば待機を既定にし、確定済みだけ出す場合は明示確認。スマホ内の未送信件数はPCから確定できない旨を表示 |
| 終了の確定 | DBの一貫した読取結果から出力列だけの行データを固定し、`inspection_exports`へ点検ID・版・対象ID・行データ・パス・SHA-256・状態を保存。画像配列やログ本文は複製しない。CSV保存成功後に終了扱い。失敗時は同じ行データで再試行 |
| 再出力 | `点検_日付_点検ID_r001.csv`から連番で新規作成。変更後は対象を再確認してr002、過去のCSVとDB内の出力記録は維持。二重クリックは同じ処理として扱う。保存直後の異常終了はパスとハッシュで照合して復旧 |

理由は表の内容をDBから再現し、再処理後も提出済みの内容を追えるため。全履歴への上書き出力は採らない。

## 3. 保存形式と置き場所

推奨案は既存のCSV出力を再利用し、UTF-8 BOM・CRLF・標準CSV引用で保存する。Excelで扱いやすく、追加依存が要らない。xlsxは型・桁の固定に有利だが、初版では見送る。文字列列の数式開始文字は無害化し、数値列の負数は維持する。

```text
Windowsのドキュメント（Known Folderで取得）
└─ メーター点検\点検_日付_ID_r001.csv
%LOCALAPPDATA%\SotukenMeter\
├─ manager.db
├─ config\pc_config.json
├─ incoming\              画像と付随JSON
├─ images\                原画像
├─ logs\                  読み取り・起動ログ
├─ overlays\              検出結果画像
├─ models\                manifests・blobs
├─ runtime\status.json    監視の待ち件数・処理中状態
└─ backups\               移行前DB
%LOCALAPPDATA%\Programs\SotukenMeter\
└─ アプリ・Python依存・Ollama本体（実行用）
```

`manager/paths.py`で保存先を決め、受信口・監視・USB・画面へ同じ絶対パスを渡す。重複する`receiver.py`と`usb_pull.py`の`get_default_incoming_dir`もここへ集約する。実行時の作業フォルダやProgram Filesへ保存しない。

CSVは出力先と同じフォルダの一時ファイルへ書き、閉じてから未使用名へ移す。Excelで以前のCSVを開いていても新しいCSVを保存できる。ロック・権限・容量不足では完了扱いにせず、保存先変更か再試行を案内する。画面に「表のフォルダを開く」を置く。OneDrive配下への保存は同期対象になるため、場所を初回に表示する。

## 4. 同梱物とサイズ

推奨案はWindows x64・Python 3.11の専用ビルド環境でPyInstallerの`onedir`を作り、インストーラーにまとめる。理由は起動のたびの展開を避け、DLL・OCRモデル・Streamlitの静的ファイルを確認しやすいため。依存版を固定し、`app.py`から動的に読み込むモジュールもspecへ明記する。

| 実測対象（2026-10-30、このPC） | 容量・確認方法 |
|---|---|
| venv全体／Python | 556,297,091 bytes（530.5 MiB）。`Get-ChildItem -Recurse -File`のLength合計。Python 3.11.14、`venv\Scripts\python.exe -m pip list --format=json`で依存版を確認 |
| 主な依存 | cv2 121.0／pyarrow 77.8／numpy 55.2／pandas 41.7／RapidOCR 31.1／ONNX Runtime 30.8／Streamlit 25.2 MiB。OCRのONNXモデル3個がローカルに存在 |
| Ollama本体 | インストール済み0.40.13は3,327,691,171 bytes。CUDA・ROCm等を含む。配布ZIPそのものの容量ではない |
| `qwen3-vl:4b-instruct` | 主モデル等は約3.296 GB。現環境のmanifestを再帰的にたどると、別runnerのモデル・projectorも含め10個の固有blob、6,631,490,022 bytes。全参照ファイルの存在を確認 |
| 容量の推測 | 現環境相当を全部入れると展開後約10.5 GB、配布一式は圧縮後5〜9 GBと仮置き。3.3 GBの構成だけで動けば展開後約7.2 GB。圧縮率は未測定。初版の空き容量目安はインストーラー・展開・更新待避込み30 GB、ビルド後に補正 |

| 方式 | 比較と推奨 |
|---|---|
| 本体・モデルを同梱して`OLLAMA_MODELS`へ配置 | 推奨。インターネットなしで初回利用できる。本体は公式standalone ZIP、モデルは隔離環境で取得した固定版のmanifestと必要なblob一式。参照とハッシュを検査し、初回通信が不要か試す |
| 初回に`ollama pull` | 配布は小さくなるが、数GBの通信・接続失敗・モデル更新が初回利用を妨げ、同梱決定も満たさない |
| 既存Ollamaを共用 | 容量を節約できるが版・モデル・利用中の負荷が他アプリに依存。初版は専用プロセスを推奨 |
| USBのadb | 初版は任意機能。必要な人だけ公式platform-toolsと端末ドライバーを導入し、`ADB`へ絶対パスを設定。USBデバッグ許可も必要。同梱案は導入を減らせるが、再配布条件・ドライバー・既存adbとの競合の確認が増える |

専用Ollamaはアプリ起動中だけ`127.0.0.1:11435`で動かす。`OLLAMA_HOST`・`OLLAMA_MODELS`は子プロセスとPythonクライアントへ渡し、利用者の環境変数や既存11434を変えない。競合時は他プロセスを止めずエラーを表示。API応答だけでなくモデル名・digestと試行推論を確認する。

| 公式資料 | 確認した根拠 |
|---|---|
| [PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html) | Python同梱、onedir／onefile、動的importとデータファイルの追加指定 |
| [Ollama Windows](https://docs.ollama.com/windows)・[FAQ](https://docs.ollama.com/faq)・[モデル一覧](https://ollama.com/library/qwen3-vl/tags) | standalone ZIP、保存先・ホスト設定、モデルの公称約3.3 GB |
| [Inno Setupの容量制限](https://jrsoftware.org/ishelp/topic_setup_diskspanning.htm) | 圧縮後4,200,000,000 bytes超はDiskSpanningが必要 |

## 5. インストーラーの作り方

推奨案はInno Setupでユーザー単位のインストールとし、スタートメニューに「メーター点検」と「点検表」を作る。管理者権限を常用せずに済むため。全ユーザー向けProgram Files配置は、管理者による配布が必要になった段階で検討する。

Inno Setupは上記容量を超えると単一exeにできない。初回ビルドで測り、超える場合は`Setup.exe + Setup-*.bin`を一つのZIPで配布する案を確認する。巨大なモデルをアプリのonefileへ埋め込む方法は採らない。

| 段階 | 起動・終了の設計 |
|---|---|
| 起動準備 | 多重起動防止、パス解決、DB移行、Ollama起動開始。確認・試行推論は非同期にして受信・画面を待たせず、監視の推論開始だけ待機。現行`run_pc.py`は受信口スレッドとStreamlitだけで、監視・USBは未起動 |
| 通常起動 | 受信口8765→取り込み監視→有効時だけUSB→画面8501。監視を登録してから初回走査し、起動間の到着分と既存ハッシュを照合して一度だけ処理。`--use-vlm`を有効にする（現行監視の既定は無効） |
| プロセス管理 | 受信口とStreamlitは現行構成を活かす。監視・USBは同梱exeの役割別引数で起動。`sys.executable -m`に依存しない。監視は`runtime/status.json`を一時ファイル経由で更新し、画面へ件数・稼働時刻を伝える。更新停止は状態不明とする。画面は127.0.0.1限定、受信口だけLAN公開 |
| 画面 | 既定ブラウザのタブを推奨。追加ランタイムが不要。Edgeの`--app`による専用ウィンドウは環境依存、WebView2は梱包・検証が増える。タブを閉じても待受継続と表示し、アプリの終了操作で自分の子だけ停止 |
| 初回の通信 | TCP 8765のプライベートネットワーク許可とスマホの送信先を案内。公開ネットワークへ広げない。管理PCで拒否された場合は管理者へ依頼。8501・11435はファイアウォールで外へ開けない |
| アンインストール | アプリ本体・ショートカット・作成した通信規則だけ削除。表・DB・設定・画像・ログ・モデルは保持し、削除は別の明示操作 |

## 6. 更新と配布

推奨案は版番号とSHA-256を添えた手動配布。自動更新は配布先が増えてから検討する。モデルが変わらない更新ではモデルを再配布せず、更新版が要求するdigestの存在を検査する。

DBは`PRAGMA user_version`で順に移行する。全書込プロセスを停止し、SQLiteのbackup APIで退避してからトランザクションで変更する。失敗時は起動を止めて復旧し、未知の新しいスキーマは開かない。旧リポジトリのデータは明示選択してコピーし、画像等のパスを変換・検査してから切り替える。元データは残す。理由はアプリ更新とデータ破損を切り離すため。

## 7. リスクと確認事項

推奨案は小さな配布試作を先にクリーンなWindowsで試すこと。開発PCだけで確認する別案では、既存Python・DLL・モデルへの依存を見落とす。

| リスク | 先に確かめる方法・合格条件 |
|---|---|
| DLL・OCRモデル・Streamlit梱包漏れ | Python・Ollama未導入のWindows 11 x64で、通信を切ってOCRとVLMの両経路を実行。cv2・ONNX Runtime・VC++ランタイム、OCRモデル、静的資産の不足を確認 |
| 日本語パス・権限・画像参照 | 日本語ユーザー名・空白・書込禁止の作業ディレクトリで受信→保存→CSV。指定したデータ領域だけが変化。旧DB移行後も全画像が開く |
| 時刻・表の誤認 | 撮影から遅れて送信、USB再送、後着JSON、再処理を比較。撮影・取込・処理後保存の順序と欠損を確認。旧保存時刻を撮影時刻にしない |
| CSV・出力中断 | Excelで旧版を開く、数式に見える名称、改行・カンマ、空き容量不足、保存直後の強制終了。上書き・偽の完了・二重版がない |
| Ollama待機・ポート競合 | 既存11434稼働、11435占有、モデル破損、CPUのみ・GPU不足を試す。推奨タイムアウトは起動60秒・初回試行180秒、失敗理由と再試行を表示。画像は未処理のまま保持 |
| 1枚約22秒・初回約28秒 | 依頼元の既測値で、今回再測定はしていない。対象PCで3枚を測り、待ち件数・処理中・完了を表示。3枚約66秒は推測であり、CPU環境では再測定が必要 |
| 誤検知・配布制限 | 最終exeをDefender・SmartScreenで確認し、署名とハッシュを用意。保護を無効化させない。Ollama・モデル・OCR等のライセンスとNOTICE、Inno Setup利用条件を配布前に確認 |
| 終了・更新・USB | 監視処理中の終了、再起動、更新中断、USB未許可を試す。未処理画像を再開でき、既存Ollama・adbを一括終了しない。削除後も表とDBが残る |

## 8. タスク分解

推奨案は表の書き出しを先に独立して実装する。理由はインストーラーがなくても価値が出るため。全体を一括変更する別案は、保存先・時刻・配布の問題を分離しにくい。下表は変更予定ファイルで、各タスク5ファイル以内。担当者の割当はメインが行う。

| 順序・依存 | 作業／対象ファイル | 受け入れ条件 |
|---|---|---|
| T1・なし | 点検と表。 `manager/export.py`, `manager/inspection.py`新規, `manager/storage.py`, `app.py`, `tests/test_export.py` | 既存DBから選択分を終了操作でCSV保存。新設時刻・単位は空欄。名称修正、判定、二重押下、再起動、ロック・中断・再出力を確認。既存CSV仕様のテストを更新 |
| T2・T1 | 共通保存先。 `manager/paths.py`新規, `manager/storage.py`, `manager/manager.py`, `manager/inspection.py`, `tests/test_paths.py`新規 | Known Folder・LocalAppDataで絶対パスが決まり、明示したテスト用パスは優先 |
| T3a・T2 | 受信・USBの保存先。 `manager/receiver.py`, `manager/usb_pull.py`, `tests/test_receiver.py`, `tests/test_usb_pull.py` | 同じincomingを指し、重複関数を解消。既存テストのパス期待値を更新 |
| T3b・T3a | 監視・画面の保存先。 `manager/watch_inbox.py`, `app.py`, `tests/test_runtime_paths.py`新規 | 受信・監視・USB・画面で同じDB／incomingを確認 |
| T4・T2 | 画像・ログの保存先。 `manager/ingest.py`, `manager/manager.py`, `manager/reprocess.py`, `manager/image_store.py`, `tests/test_ingest.py` | ログの直書きと相対パスを解消し、作業フォルダを変えて画像・ログ参照が切れない |
| T5・T1 | 時刻・単位のDB契約。 `manager/storage.py`, `manager/sidecar.py`, `tests/test_storage.py`, `tests/test_sidecar.py` | nullable列を段階移行。旧timestamp保持。日時の不正値・タイムゾーン欠損は撮影時刻として補完しない |
| T6・T3a,T5 | HTTP/USBの取込時刻。 `manager/receiver.py`, `manager/usb_pull.py`, `tests/test_receiver.py`, `tests/test_usb_pull.py` | PC側で到着完了時刻を付随JSONへ記録。送信者のreceived_atは信用せず、再送で最初の取込時刻を上書きしない |
| T7・T4,T5,T6 | DBへの時刻引継ぎ。 `manager/ingest.py`, `manager/manager.py`, `manager/reprocess.py`, `manager/export.py`, `tests/test_ingest.py` | 撮影・取込時刻と通常取込の処理版を保存。後着JSON・手動画像・再処理でも出所を保ち、未知値を偽装しない |
| T8a・T3b,T7 | 監視状態の共有。 `manager/watcher.py`, `manager/watch_inbox.py`, `manager/paths.py`, `tests/test_watcher.py` | 待ち件数・処理中・稼働時刻をstatus.jsonへ保存。監視登録と初回走査の間の到着も一度だけ処理 |
| T8b・T1,T8a | 終了前確認と単位入力。 `app.py`, `manager/inspection.py`, `manager/storage.py`, `tests/test_export.py` | DBへ単位保存。処理待ちと未設定件数を示し、確定対象だけ出力。終了後の到着分は追加候補として提示 |
| T9・T3b,T4,T7 | 旧データ移行・復旧。 `manager/migrate.py`新規, `manager/storage.py`, `manager/paths.py`, `tests/test_migration.py`新規 | 稼働停止下のbackup・user_version・失敗復旧・画像パス変換・元データ保持を確認 |
| T10・T8b,T9 | 起動管理。 `run_pc.py`, `manager/runtime.py`新規, `manager/watch_inbox.py`, `app.py`, `tests/test_runtime.py`新規 | 3役割の起動、Ollama準備、VLM有効、状態表示、多重起動防止、自分のプロセスだけ終了 |
| T11・T10 | 配布試作。 `packaging/pc.spec`, `packaging/requirements-build.txt`, `packaging/build.ps1`, `packaging/THIRD_PARTY_NOTICES.txt`を新規 | 依存・処理版を固定。OCRモデルとOllamaモデル参照を検査。offlineで両経路が通り、圧縮前後の容量を測定 |
| T12・T11 | インストーラー。 `packaging/setup.iss`, `packaging/verify_install.ps1`を新規, `SETUP.md` | Pythonなしでインストール→無線3枚→終了CSV→更新→アンインストールを確認。表・DB保持、初回通信不要、サイズ制限内の配布形式を確定 |

