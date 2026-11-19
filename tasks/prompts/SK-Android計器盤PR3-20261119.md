この指示は2026-11-19（11/18の作業終了後）に作りました。次回の作業日に使います。家で進めても構いません。

--- ここから OpenCode に貼る ---
【研究の概要と全体構成】
この研究は、工場の丸型アナログメーターをスマホで撮影し、PCで針の位置を読み取って記録するシステムを作っています。
処理の流れは次のとおりです。
1. Androidアプリ（`android/`、Kotlin・Jetpack Compose）：点検を作り、機器QRまたは一覧から機器を選んで撮影します。点検を完了するとPCへ自動送信します。
2. PC受信口（`manager/receiver.py`）：ポート8765で写真を受け取ります（合言葉つき）。
3. 取り込み（`manager/watch_inbox.py` → `ingest.py`）：届いた写真を読み取り、1枚約10秒で処理します。
4. データベース：SQLite（`manager.db`）に保存します。
5. PC画面：今はStreamlit（`app.py`）で動かしており、React版へ移行中です。
開発環境はOSがWindows、シェルがPowerShell、GitHubリポジトリは `H3Y-dev/sotuken` です。

【これまでの経緯と、今回の作業の位置づけ】
0. 前回の到達点
- 設計書 `tasks/design/Android-計器盤デザイン.md` のPR1（テーマと色・文字のトークン）は PR #146 で `main` にマージ済みです。
- PR2（ブランチ `feat/android-gauge-2`、コミット `ee62ba6`、共通部品と見出し・接続帯）は push 済みです。11/19に大久保側で確認した結果、変更ファイルは指定の8つだけ、単体テスト363件OK、`assembleDebug` 成功でした。ただし `main` 向けのPRはまだありません。
- `main` は11/18〜19に PR #143〜#164 で大きく動きました（React版PC画面の土台・ログインの仕組み・受信状態/進捗/一覧・機器の表と機器API・機器登録の画面・デモ用DB作成ツール・Androidの計器盤デザインPR1・受信口テストの不安定修正）。`main` の先頭は `d7ac955` かそれより新しいです。
- テスト件数: Python 753件OK（main `d7ac955`）、Android 単体テスト 363件OK（Java 21）。

今回やるのは、*PR2のPRを出すこと* と、*PR3 `feat/android-gauge-3`（言葉をそろえる：未着理由・台・ルート／送信状況の行の理由）* です。PR4以降は今回やりません。

【あなたがやること（この順番で進める）】
1. PR2のPRを出す（`-c` は付けない。既にあるブランチです）
`git fetch origin`
`git switch feat/android-gauge-2`
`git rebase origin/main`（衝突したら直さずに止まって報告する）
PowerShellで `$env:JAVA_HOME` を Java 21（例: `C:\Program Files\Android\Android Studio\jbr`、または前回うまくいった `C:\Users\marir\.jdks\jbr-21.0.11`）に設定する。
`cd android`
`.\gradlew.bat testDebugUnitTest`（363件・`BUILD SUCCESSFUL`）
`cd ..`
`git push --force-with-lease origin feat/android-gauge-2`
GitHubで `main` 向けPRを作る。説明に「設計書 `tasks/design/Android-計器盤デザイン.md` の PR2」と書く。接続帯3状態のスクショがあれば添える。マージは大久保が行う。

2. PR3のブランチを作る
設計書の決まりでは「前のPRがマージされてから次を始める」です。
- PR2 が `main` にマージ済みなら: `git switch main` → `git pull` → `git switch -c feat/android-gauge-3`
- まだマージされていなければ: `feat/android-gauge-2` にいる状態で `git switch -c feat/android-gauge-3`。PRのベースは `feat/android-gauge-2` にする（PR2のマージ後に大久保がベースを `main` へ付け替える）。

3. 設計書の読み込みと着手前テスト
`tasks/design/Android-計器盤デザイン.md` の「2章の言葉の表」「4.3節」「5.1節」「5.2節」「5.3節」「5.4節」「## 7. 実装の分割」（冒頭の共通の決まりとPR3の行）を読む。
`cd android` → `.\gradlew.bat testDebugUnitTest` で着手前の件数を控える。

4. PR3の実装（設計書のPR3の行に書かれたものだけ。ponytail・最小の実装で）
- 5.1節の表のファイル: `ConnectionStatus.kt`・`QueueDisplay.kt`・`QueueListScreen.kt`・`MeterCaptureApp.kt`・`PairingScreen.kt`・`InspectionDisplay.kt`・`InspectionSendStatusScreen.kt`・`ConnectionGuideScreen.kt`・`InspectionCreateScreen.kt`・`RouteListScreen.kt`・`InspectionApp.kt`
- 4.3節の `reasonFromLastError`・`undeliveredReason`、`errorTextFor` の書き換え
- 5.3節の `SendRow.reason`
- 5.4節のテストの期待値（直してよい期待値は5.4節の行だけ）
- テストを1つ足す: `QueueDisplayTest` に `reasonFromLastErrorMapsRawErrors`。R1〜R7 を各1行の `assertEquals` で書く。例 `assertEquals("合言葉が違います", reasonFromLastError("PC未接続: Health check failed with HTTP 401: x"))`。それに加えて `assertEquals("接続できません", reasonFromLastError("PC未接続: 接続できません"))` の1行。
- コメントに残る旧い言葉（例: `QueueDisplay.kt:7`・`:35`・`:53`）も、2章の表に従って書き換える。

5. テスト・ビルド・旧文言の確認
`cd android` で次を実行し、両方 `BUILD SUCCESSFUL` になること。テストを1つ足すので、件数は着手前より1件増えるはず（363 → 364）。
`.\gradlew.bat testDebugUnitTest`
`.\gradlew.bat assembleDebug`
リポジトリ直下で次を実行する。出てよいのは M1（5.2節）の比較に使う `"PCに届かないため、写真の一覧を送れませんでした"` の1行だけ。
`git grep -n -e 未到着 -e 届いていません -e 届かない -e PC受信済み -e "機器）" -e 対象一覧 -e 一覧外 -- android/app/src/main/kotlin/jp/sotuken/metercapture/ui`

6. コミット・push・PR作成
`origin feat/android-gauge-3` へpushし、PRを作る（ベースは手順2で決めたもの）。説明に「設計書 `tasks/design/Android-計器盤デザイン.md` の PR3」と書く。マージは大久保が行うため、自分ではマージしない。

【終わったら続けてやること】
`.\gradlew.bat installDebug` で実機（SO-52E）に入れ、確認する画面を撮る：送信状況（未着がある点検。PCを止めて完了→送信待ちで「理由：接続できません」が出る）。

【守るルール】
- PR3の行に書かれたファイルだけ触る。
- 触らないもの: `ui/` 以外のKotlin（`queue/`・`inspection/`・`settings/`・`pairing/`・`route/`・`device/`・`capture/`・`MainActivity.kt`）、送信・保存・QR・ネットワークの処理、`build.gradle.kts`・`libs.versions.toml`（依存を足さない）。
- 既存の日本語の文字列リテラルは、5.1節の表で指定された置き換え以外は変えない。
- 止まる条件: 本体（`ui/` 以外）のバグを見つけた、表に無いテストが落ちた、設計書と実物の行番号・中身が食い違う。このどれかのときは直さずに止まって報告する。
- テストが落ちたときにアサーションを緩めない。分からなければ止まって報告する。
- 頼まれていない機能・テスト・抽象化を足さない。アニメーションを足さない。
- メーター写真・`manager.db`・合言葉をSlackや外部に貼らない。
- 迷ったら推測で進めず、止まって質問する。コマンド出力やテスト結果を捏造しない。

【最後に作ってほしいもの】
A. Slackに貼る短い要約（箇条書き・表 `|` 禁止・太字は `*太字*`）
- PR2のPRのURL
- PR3の実装内容とPRのURL
- テスト（着手前後の件数）とビルドの結果、旧文言の `git grep` の結果
- 実機確認の有無

B. リポジトリ外に保存する日報（ファイル名: `日報_SK_<作業日YYYYMMDD>.md`）の8項目
1. 名前と日付
2. 今日のタスク名
3. やったこと
4. 成果物
5. テスト結果（着手前後の件数）
6. 受け入れ条件の達成状況（PR2のPRが出ているか／PR3の受入条件のうち達成・未達）
7. 詰まったところ
8. 次に必要なこと・大久保さんに判断してほしいこと

では、手順 1 から始めてください。
--- ここまで ---
