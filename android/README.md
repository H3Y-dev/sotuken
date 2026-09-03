# メーター撮影 Androidアプリ（雛形）

## 役割

工場内の丸型アナログ計器を端末で撮影し、**画像だけ**をPCへ渡すためのAndroidアプリです。画像から圧力・温度などの値を読み取ったり、数値を算出したりする処理は、このアプリには実装しません。読み取りと数値化はPC側のPythonが担当します。

通信できない工場内でも撮影を溜められるよう、送信対象は端末内のキューに1本だけ保持します。将来の送信出口はHTTPと、公開フォルダへの画像・JSON書き出しです。

## Android Studioで開く・ビルドする

1. [Android Studio](https://developer.android.com/studio) をインストールします。初回セットアップでは `Standard` を選び、Android SDK と Android SDK Platform-Tools のインストールを完了します。
2. Android Studioを起動し、`Open` を選びます。
3. `C:\卒研\git_stk\sotuken\android` を選んで開きます。**リポジトリのルートではなく、この `android` フォルダを開きます。**
4. SDKが見つからない場合は、画面の案内に従ってSDKの場所を指定します。続いて `Tools > SDK Manager` を開き、`Android 16.0 (API 36)` の SDK Platform をインストールします。**API 36 です。35ではありません。**
5. Android Studioが表示する `Sync Now` を押し、Gradle同期が終わるまで待ちます。JDKはAndroid Studio同梱のもの（JBR）を使ってください。自分でインストールしたJDKを指定すると、バージョンが古くて失敗することがあります。
6. メニューの `Build > Make Project` を選びます。成功すれば雛形のビルド確認は完了です。

コマンドラインでビルドする場合は、PowerShellで次を実行します。

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd C:\卒研\git_stk\sotuken\android
.\gradlew.bat assembleDebug
```

`JAVA_HOME` の行を省くと、PATHにある古いJDK（JDK 11など）が使われてビルドが失敗します。Android Studioのインストール先が違う場合はパスを読み替えてください。

## ユニットテストを走らせる

実機もエミュレータも不要です。

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd C:\卒研\git_stk\sotuken\android
.\gradlew.bat test
```

`app/src/test/kotlin/` にあるJVMユニットテストが走ります。結果のレポートは `app/build/reports/tests/testDebugUnitTest/index.html` をブラウザで開くと読めます。

## 実機で起動する

1. Android端末の `設定 > 端末情報` を開き、`ビルド番号` を7回タップして開発者向けオプションを有効にします。画面ロックのPINなどを求められたら入力します。
2. `設定 > システム > 開発者向けオプション` で `USBデバッグ` をオンにします。機種によって項目の場所は少し異なります。
3. USBケーブルで端末をPCへ接続し、端末のロックを解除します。
4. 端末の通知を開き、`USBの用途` を **`ファイル転送`**（機種により `MTP` / `ファイル転送/Android Auto`）に変更します。`充電のみ` のままだと、PCから端末が見えない機種があります。
5. 端末に「USBデバッグを許可しますか」と表示されたら、**「このパソコンからのUSBデバッグを常に許可する」にチェックを入れて**許可します。
6. Android Studio上部のデバイス選択欄で接続した端末を選び、緑の実行ボタン（Run）を押します。
7. 初回はアプリのインストールに少し時間がかかります。起動後に「メーター撮影」と「キュー: 0件」が表示されれば、この雛形の確認は完了です。

現時点ではカメラを使わないため、権限の実行時リクエストはまだ表示されません。**画面に出るのはタイトルと「キュー: 0件」だけです。**キューへ入れる手段がまだ無いので、件数は常に0のままが正常です。ボタンも一覧も出ません。

### 端末が認識されているか確かめる

Android Studioのデバイス欄に出ないときは、コマンドで確かめると原因を切り分けられます。

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices
```

| 出力 | 意味と対処 |
| --- | --- |
| `<端末ID>  device` | 正常。認識できています |
| 何も出ない | USBデバッグがオフ、`USBの用途` が `充電のみ`、またはケーブルが充電専用。**データ転送対応のケーブルを使ってください**。ケーブル起因はよくあります |
| `<端末ID>  unauthorized` | 端末側の許可ダイアログが未応答。端末のロックを解除して許可します。出てこない場合は `開発者向けオプション > USBデバッグの許可の取り消し` を実行してから繋ぎ直します |
| `<端末ID>  offline` | ケーブルを抜き差しし、`adb kill-server` の後にもう一度 `adb devices` を実行します |

APKを直接インストールしたい場合はこうします。

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r "C:\卒研\git_stk\sotuken\android\app\build\outputs\apk\debug\app-debug.apk"
```

### エミュレータでもよいか

日常の開発では使えますが、**エミュレータにカメラはありません**（仮想の映像が出るだけです）。この研究は実際の計器を撮影するのが目的なので、**カメラを扱う作業（Sprint 3以降）と工場での確認は実機が必須**です。起動確認だけならエミュレータでも構いません。

## ディレクトリ構成と担当

```text
android/
├── app/
│   └── src/main/
│       ├── kotlin/jp/sotuken/metercapture/
│       │   ├── queue/     # 本人（大久保）
│       │   └── ui/        # SKくん
│       ├── res/
│       └── AndroidManifest.xml
├── gradle/libs.versions.toml
├── gradle/wrapper/
├── build.gradle.kts
└── settings.gradle.kts
```

| 領域 | 担当 | 内容 |
| --- | --- | --- |
| `queue/` | 本人（大久保） | データモデル・状態遷移・送出の抽象化・再送・保持ポリシー |
| `ui/` | SKくん | カメラ撮影・ガイド枠表示・リスト画面・入力フォーム |

## 2人の境界

`ui/` が `queue/` を使う入口は、`QueueStore` の次の2関数だけです。引数・戻り値を変更する場合は、2人で合意してから変更してください。

```kotlin
suspend fun enqueue(imageFile: File, meta: CaptureMeta): String
fun observeQueue(): Flow<List<QueueItem>>
```

`enqueue` は画像ファイルと任意入力のメタデータをキューへ入れ、端末内ID（`localId`）を返します。`observeQueue` は画面表示用にキュー全件をFlowで通知します。

## TODOについて

未実装の箇所はすべて `// TODO(本人): ...` または `// TODO(SKくん): ...` の形で、担当者と予定スプリントを明記しています。担当外のTODOを先回りして実装せず、該当スプリントで担当者が実装してください。


## ビルドで詰まったときは

2026-09-03、この雛形を初めてコマンドラインでビルドしたときに実際に起きたものです。同じエラーが出たら、まずここを見てください。

### `Your project path contains non-ASCII characters`

リポジトリのパスに日本語（`卒研`）が入っているためです。`android/gradle.properties` に次の1行を入れて回避しています。既に入っているので、消さないでください。

```
android.overridePathCheck=true
```

これを入れた状態で `gradlew test` と `assembleDebug` が通ることは確認済みです。もし将来これでも通らない不具合が出たら、リポジトリごと ASCII だけのパス（例: `C:\work\sotuken`）へ移す必要があります。

### `SDK location not found`

`android/local.properties` が無いか、中身が壊れています。このファイルはGit管理外なので、**各自が自分の環境で1回作ります。** 内容は1行だけです。

```
sdk.dir=C:/Users/<自分のユーザー名>/AppData/Local/Android/Sdk
```

区切りはバックスラッシュではなく**スラッシュ**で書いてください。またPowerShellの `Out-File` や `>` で作るとファイル先頭にBOMが付き、この1行が読まれずに同じエラーが出ます。メモ帳やAndroid Studioのエディタで作るのが確実です。Android Studioでプロジェクトを開けば自動生成されるので、通常は自分で作る必要はありません。

### `requires Android Gradle plugin 9.1.0 or higher` / `requires ... compile against version 37 or later`

依存ライブラリのバージョンが、このプロジェクトのAGP（Android Gradle Plugin）より新しすぎるときに出ます。`gradle/libs.versions.toml` のバージョンは**AGP 8.13.2 で通る組み合わせに揃えてあります。**

| 項目 | 値 | 理由 |
| --- | --- | --- |
| `agp` | 8.13.2 | 各自のAndroid Studioで開けることを優先し、上げていない |
| `compileSdk` / `targetSdk` | 36 | AGP 8.13.2 が扱える上限 |
| `composeBom` | 2026.06.01 | これより新しいBOMは Compose 1.12 系を引き、AGP 9.1 を要求する |
| `lifecycle` | 2.10.0 | 2.11.0 は AGP 9.1 を要求する |

**ライブラリのバージョンを勝手に上げないでください。** 上げる必要が出たら、AGPとcompileSdkもセットで上げる話になるので、大久保へ相談してください。

### PATHのJDKが古い

`gradlew` は `JAVA_HOME` のJDKを使います。指定しないとPATHにある古いJDK（この環境では11でした）が使われ、AGP 8.13.2 が要求するJDK 17以上を満たさず失敗します。上のコマンド例のように毎回 `JAVA_HOME` を指定するか、環境変数に設定しておいてください。Android Studioから実行する場合は同梱JDKが使われるので、この問題は起きません。
