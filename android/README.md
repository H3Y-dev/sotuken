# メーター撮影 Androidアプリ（雛形）

## 役割

工場内の丸型アナログ計器を端末で撮影し、**画像だけ**をPCへ渡すためのAndroidアプリです。画像から圧力・温度などの値を読み取ったり、数値を算出したりする処理は、このアプリには実装しません。読み取りと数値化はPC側のPythonが担当します。

通信できない工場内でも撮影を溜められるよう、送信対象は端末内のキューに1本だけ保持します。将来の送信出口はHTTPと、公開フォルダへの画像・JSON書き出しです。

## Android Studioで開く・ビルドする

1. [Android Studio](https://developer.android.com/studio) をインストールします。初回セットアップでは `Standard` を選び、Android SDK と Android SDK Platform-Tools のインストールを完了します。
2. Android Studioを起動し、`Open` を選びます。
3. `C:\卒研\git_stk\sotuken\android` を選んで開きます。**リポジトリのルートではなく、この `android` フォルダを開きます。**
4. SDKが見つからない場合は、画面の案内に従ってSDKの場所を指定します。続いて `Tools > SDK Manager` を開き、`Android 15.0 (API 35)` の SDK Platform をインストールします。
5. Android Studioが表示する `Sync Now` を押し、Gradle同期が終わるまで待ちます。JDKはAndroid Studio同梱のJDK 17を使ってください。
6. メニューの `Build > Make Project` を選びます。成功すれば雛形のビルド確認は完了です。

コマンドラインでビルドする場合は、PowerShellで次を実行します。

```powershell
cd C:\卒研\git_stk\sotuken\android
.\gradlew.bat assembleDebug
```

## 実機で起動する

1. Android端末の `設定 > 端末情報` を開き、`ビルド番号` を7回タップして開発者向けオプションを有効にします。画面ロックのPINなどを求められたら入力します。
2. `設定 > システム > 開発者向けオプション` で `USBデバッグ` をオンにします。機種によって項目の場所は少し異なります。
3. USBケーブルで端末をPCへ接続し、端末のロックを解除します。端末に「USBデバッグを許可しますか」と表示されたら、PCのRSAキーを許可します。
4. Android Studio上部のデバイス選択欄で接続した端末を選び、緑の実行ボタン（Run）を押します。
5. 初回はアプリのインストールに少し時間がかかります。起動後に「メーター撮影」と「キュー: 0件」が表示されれば、この雛形の確認は完了です。

現時点ではカメラを使わないため、権限の実行時リクエストはまだ表示されません。

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

