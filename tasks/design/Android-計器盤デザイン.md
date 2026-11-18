合意: 2026-11-18 方向性と0章の決定をユーザー確認済み（React版計器盤と同じ雰囲気）

# Android アプリ「計器盤」デザイン刷新 設計書

対象: `android/app/src/main/kotlin/jp/sotuken/metercapture/ui/` 以下の画面（Kotlin・Jetpack Compose・Material 3）
見本: React版「計器盤」（`prototypes/react-records/DESIGN.md`、`feat/gauge-design-polish` `312e849` で「合意: 済」。色・角丸・書体の値は `3276536` と同じ）
実装する人: SKくん（OpenCode）。この設計書は PR ごとの作業（7章）に分けてあり、1章ずつ OpenCode に渡せば実装できる細かさで書いてある。

---

## 0. 決定事項

1. **決定（2026-11-18 ユーザー）**: 点検中の履歴の札は「完了後に送信」のままにする。点検中の写真を送る仕様変更はせず、履歴の行に「今すぐ送る」ボタンを作らない。
2. **決定（2026-11-18 ユーザー）**: BIZ UDPゴシックは同梱せず端末の標準書体を使う。PR7（書体の同梱）は当面しない。
3. **決定（2026-11-18 ユーザー）**: 言葉の置き換えを採用する。「件」は写真では「枚」、機器では「台」。「機器」は「台」、「対象一覧」は「ルート」、「一覧外」は「ルート外」、「送信箱」は「端末」に置き換える。
4. **決定（2026-11-18 ユーザー）**: SKくんの11/12日報の原文を読めていないことは了承済み。本書はvaultの要約から設計した。
5. **決定（2026-11-18 ユーザー）**: 送信済みでも未撮影・重複・機器IDなしがあれば、中立の「送信済み（要確認あり）」を採用する。
6. **決定（2026-11-18 ユーザー）**: React版 DESIGN.md の Android 対応節との差2点は了承済み。状態色は `CompositionLocal` を使わず `object GaugeColors` で参照し、書体は同梱しない。

---

## 1. 方向性

- React版「計器盤」と同じ雰囲気にする。
  - 明るい灰色の盤面（`#E3E6E4`）に、文字盤の白（`#F8F8F5`）のカードを置く。
  - 数字と主ボタンは記録計の紺インク（`#1D3A63`）。
  - 状態は「色・文字・形」の3つで示す。
- **正常は控えめ、問題は塗り。** 正常は薄い緑の地に緑の文字。要確認（黄土）と失敗（赤錆）は塗りに白い文字。一覧で問題のある所だけが目に入るようにする。
- **未撮影・未着・失敗・要確認が1つでもあれば、緑の札を出さない**（React版の「受信・完了状態」の考え方）。
- **SK-08の短い白い光以外の動きは付けない。** React版の「動き」の節（針の回転・段の色の移り変わり）は、スマホでは使わない。点滅・脈打つ動き・読み込みの飾り・画面遷移のアニメーションも付けない。Compose の `animate*`・`AnimatedVisibility`・`Crossfade` は使わない。
- **文字盤の絵は移植しない。** スマホには読み取り値が無い。React版は、値を表さない飾りとしての文字盤を禁止している。計器の意匠として使ってよいのは、画面見出しの下の目盛りの定規（`TickRule`）だけ。
- **屋外・工場の明るさで読める大きさとコントラストにする。**
  - 本文は最小16sp。
  - 押せる所は高さ48dp以上。
  - 文字と地のコントラストは4.5:1以上（3.3節）。
- **ライト固定。** 端末がダークモードでもライトの配色で表示する。Android 12 以降の壁紙の色（dynamic color）も使わない。
- 禁止（React版と同じ）: グラデーション、影の重ね、光彩、紫系の色、絵文字のアイコン、大文字英語の字間を広げた見出し、中央揃えの多用、背景の模様。

---

## 2. 用語と数え方（アプリ全体で統一する）

| 対象 | 使う言葉 | 使わない言葉 |
|---|---|---|
| 写真の数 | 「N枚」 | 「N件」 |
| 機器（メーター）の数 | 「N台」 | 「N機器」「N件」 |
| 点検の数 | 「N件」 | — |
| 写真がPCに届いた | 「PCに到着」 | 「PC受信済み」「送信済み(USB)」「届きました」 |
| 写真がPCに届いていない | 「PCに未着」、数は「未着 N枚」 | 「未到着」「PC未到着」「届いていません」 |
| PCとの接続がある | 「PCに接続中」 | 「PCに届きます」 |
| PCとの接続が無い | 「PCにつながりません」 | 「PCに届かない」「PCに届きません」 |
| 送信前に端末へ保存した | 「端末に保存済み」「端末に保存中」 | 「送信箱に保存中」 |
| 機器の巡回の並び | 「ルート」「ルート外」 | 「対象一覧」「一覧外」 |
| 未着の理由（行に出す） | 「理由：{理由の言葉}」（5.2節の9語のどれか） | 生のエラー文（英語・「PC未接続:」付き） |

括弧は全角の（）にそろえる（「別のPC宛て(保留)」→「別のPC宛て（保留）」）。

---

## 3. 色・文字・形・余白（トークン）

### 3.1 色トークン（`object GaugeColors`、`ui/theme/GaugeTheme.kt`）

| 名前（Kotlin） | 16進 | React版の名前 | 使う場所 |
|---|---|---|---|
| `Panel` | `#E3E6E4` | 盤面 `--g-panel` | 画面の地（`background`）、`windowBackground` |
| `PanelDeep` | `#D7DCDA` | 盤面の補助面（M3 `surfaceVariant`） | 接続帯の「確認中」の地 |
| `Dial` | `#F8F8F5` | 文字盤 `--g-dial` | カード・ダイアログの地、札（未撮影・途中・中立）の地 |
| `Text` | `#1C2226` | 墨 `--g-text` | 本文 |
| `Ink` | `#1D3A63` | 紺インク `--g-ink` | 数値、主ボタン、選択中、未撮影の破線、目盛りの定規 |
| `InkTint` | `#D9E1EC` | 紺の薄い地（M3 `primaryContainer`） | M3 内部用（画面のコードからは使わない） |
| `Steel` | `#475158` | 鋼 `--g-steel` | 補足の文字（日時・ID・出所・注記）、途中の札の文字 |
| `Rule` | `#757F85` | 罫 `--g-rule` | 入力枠、途中の札の枠 |
| `Hairline` | `#B4BBBE` | 細罫 `--g-hairline` | カードの1dp外枠、途中・中立のカード左端の4dp線 |
| `Ok` | `#2C6A45` | 正常 `--g-ok` | 正常の札の文字・枠、正常のカード左端の4dp線、接続中の帯の文字 |
| `OkTint` | `#DDEBE1` | `--g-ok-tint` | 正常の札の地、接続中の帯の地 |
| `Warn` | `#845A00` | 要確認 `--g-warn` | 要確認の札の塗り、カード左端の縞、届かない帯の地 |
| `WarnTint` | `#F4E7C6` | `--g-warn-tint` | 要確認の縞の薄い色、M3 `tertiaryContainer` |
| `Fail` | `#A23B24` | 失敗 `--g-fail` | 失敗の札の塗り、カード左端の塗り、未設定の帯の地、エラー文字、削除ボタンの文字 |
| `FailTint` | `#F5DCD5` | `--g-fail-tint` | M3 `errorContainer` |
| `OnInk` | `#FFFFFF` | `--g-on-ink` | 紺・黄土・赤錆の上の白い文字 |

`--g-band`（`#3E8A5C`、許容範囲の帯）は文字盤の絵にしか使わないため、スマホでは定義しない。

### 3.2 Material 3 の `ColorScheme`（全部の役割に値を入れる。指定漏れは M3 の紫になるため）

| 役割 | 値 | | 役割 | 値 |
|---|---|---|---|---|
| `primary` | `Ink` | | `onPrimary` | `OnInk` |
| `primaryContainer` | `InkTint` | | `onPrimaryContainer` | `Ink` |
| `inversePrimary` | `InkTint` | | `secondary` | `Steel` |
| `onSecondary` | `OnInk` | | `secondaryContainer` | `PanelDeep` |
| `onSecondaryContainer` | `Text` | | `tertiary` | `Warn` |
| `onTertiary` | `OnInk` | | `tertiaryContainer` | `WarnTint` |
| `onTertiaryContainer` | `Warn` | | `background` | `Panel` |
| `onBackground` | `Text` | | `surface` | `Dial` |
| `onSurface` | `Text` | | `surfaceVariant` | `PanelDeep` |
| `onSurfaceVariant` | `Steel` | | `surfaceTint` | `Dial` |
| `inverseSurface` | `Text` | | `inverseOnSurface` | `Dial` |
| `error` | `Fail` | | `onError` | `OnInk` |
| `errorContainer` | `FailTint` | | `onErrorContainer` | `Fail` |
| `outline` | `Rule` | | `outlineVariant` | `Hairline` |
| `scrim` | `#000000` | | `surfaceBright` | `Dial` |
| `surfaceDim` | `PanelDeep` | | `surfaceContainerLowest` | `Dial` |
| `surfaceContainerLow` | `Dial` | | `surfaceContainer` | `Dial` |
| `surfaceContainerHigh` | `Dial`（`AlertDialog` の地） | | `surfaceContainerHighest` | `PanelDeep`（M3 の塗りの `Card` の地） |

- M3 の塗りの `Card` は `surfaceContainerHighest`（灰）になる。そのため、画面のカードは M3 の `Card`／`OutlinedCard` を使わず、すべて `GaugeCard`（4.2節）に置き換える（PR4〜PR6）。

### 3.3 コントラスト（WCAG 2.x の式。React版の計算に、スマホだけで使う組を足した）

| 前景 | 背景 | 比 | 基準 | 使う所 |
|---|---|---|---|---|
| `Text` `#1C2226` | `Panel` `#E3E6E4` | 12.79:1 | 4.5:1 | 画面の本文 |
| `Text` | `Dial` `#F8F8F5` | 15.11:1 | 4.5:1 | カードの本文 |
| `Ink` `#1D3A63` | `Dial` | 10.74:1 | 4.5:1 | 数値、未撮影・中立の札 |
| `Steel` `#475158` | `Dial` | 7.63:1 | 4.5:1 | 補足、途中の札 |
| `Steel` | `Panel` | 6.46:1 | 4.5:1 | 画面の地の上の補足 |
| `Steel` | `PanelDeep` `#D7DCDA` | 5.85:1 | 4.5:1 | 接続帯「確認中」 |
| `OnInk` `#FFFFFF` | `Ink` | 11.43:1 | 4.5:1 | 主ボタン |
| `Ok` `#2C6A45` | `OkTint` `#DDEBE1` | 5.24:1 | 4.5:1 | 正常の札、接続帯「接続中」 |
| `OnInk` | `Warn` `#845A00` | 6.10:1 | 4.5:1 | 要確認の札、接続帯「届かない」 |
| `OnInk` | `Fail` `#A23B24` | 6.59:1 | 4.5:1 | 失敗の札、接続帯「未設定」 |
| `Fail` | `Dial` | 6.19:1 | 4.5:1 | エラー文字、削除ボタンの文字 |
| `Rule` `#757F85` | `Dial` | 3.85:1 | 3:1 | 入力枠、途中の札の枠 |

### 3.4 文字（`Typography`。字間はすべて `0.sp`）

| M3 の役割 | 大きさ / 行間 | 太さ | 使う所 |
|---|---|---|---|
| `displayLarge`・`displayMedium`・`displaySmall` | 44 / 44 sp | Bold | 使わない（指定漏れ防止） |
| `headlineLarge`・`headlineMedium`・`headlineSmall` | 28 / 36 sp | Bold | 画面の見出し、大きな件数（`headlineSmall` を使う） |
| `titleLarge` | 20 / 28 sp | Bold | 区画の見出し、撮影する機器名、進み具合の数（例「撮影 4/5台」） |
| `titleMedium` | 18 / 26 sp | Bold | 機器名・点検名 |
| `titleSmall` | 16 / 24 sp | Bold | 使わない |
| `bodyLarge` | 16 / 26 sp | Normal | 本文 |
| `bodyMedium` | 16 / 26 sp | Normal | 補足（色は `Steel`） |
| `bodySmall` | 16 / 26 sp | Normal | 今のコードで使っている所の救済。最小16spを守るため14にしない |
| `labelLarge` | 16 / 24 sp | Bold | ボタン、状態の札 |
| `labelMedium` | 16 / 24 sp | Bold | 今のコードで使っている所の救済 |
| `labelSmall` | 14 / 20 sp | Medium | M3 内部専用。画面のコードでは使わない |

- 書体: PR1〜PR6 は `GaugeFont = FontFamily.Default`。PR7 の書体同梱は当面しない。
- 数値（日時・ID・枚数・台数）の `Text` には、拡張関数 `TextStyle.gaugeNum()`（`fontFeatureSettings = "tnum"` を足す）を付け、桁の幅をそろえる。

### 3.5 形・余白・線

- 角丸（`Shapes`）: `extraSmall` 3dp、`small` 4dp（ボタン・札）、`medium` 6dp（カード）、`large` 6dp、`extraLarge` 6dp。
- 余白は4の倍数だけ: 4・8・12・16・20・24・32dp。
  - 画面の左右: 16dp
  - カード同士の間: 12dp
  - カードの内側: 上下16dp・右16dp・左16dp。左端の帯があるカードは、帯10dp＋16dpで左26dp
  - カードの中の行の間: 8dp
- 線: カードの外枠は `Hairline` 1dp。未撮影のカードだけ、外枠の代わりに `Ink` 2dpの破線（線6dp・間4dp）。
- 押せる所の高さ: `Button`・`OutlinedButton` は最小48dp。`TextButton` と `RadioButton` の行は、M3 の既定（触れる範囲48dp）のまま。

### 3.6 状態の5種類＋中立と、スマホの状態の対応

React版の5種類（正常・要確認・失敗・未撮影・途中）に「中立」を1つ足す。React版の Badge `tag`（「写真受信済み（要対処）」「ルート外」）に当たる。

| `GaugeKind` | 意味 | 札の見た目 | 形 | カード左端 |
|---|---|---|---|---|
| `OK` | 済んだ・問題なし | 地 `OkTint`・文字 `Ok`・枠 `Ok` 1dp | ● 塗りの丸 | `Ok` 4dpの線 |
| `WARN` | 人が見て手を打つ | 地 `Warn`・文字 `OnInk`・枠なし | ▲ 塗りの三角 | 10dpの斜めの縞（`Warn` と `WarnTint`） |
| `FAIL` | 失敗した | 地 `Fail`・文字 `OnInk`・枠なし | ■ 塗りの四角 | `Fail` 10dpの塗り |
| `MISSING` | 撮っていない | 地 `Dial`・文字 `Ink`・`Ink` 2dpの破線 | ◌ 破線の丸 | カード全体を `Ink` 2dpの破線で囲む（左端の帯なし） |
| `WAIT` | 待てば進む | 地 `Dial`・文字 `Steel`・枠 `Rule` 1dp | ◎ 二重丸 | `Hairline` 4dpの線 |
| `NEUTRAL` | 事実を示すだけ | 地 `Dial`・文字 `Ink`・枠 `Ink` 1dp | ○ 白抜きの丸 | `Hairline` 4dpの線 |

スマホの状態をどの種類に当てるかは、次のとおり。

**写真1枚の送信状態**（関数 `sendStatusLabel`・`sendStatusKind`。上の行ほど先に判定する）

| 条件 | 札の文字 | 種類 |
|---|---|---|
| `isHeldFor(現在の受信口ID)`（別のPC宛て） | 別のPC宛て（保留） | `WARN` |
| 送信対象外（点検中） | 完了後に送信 | `WAIT` |
| `PENDING` | 未送信 | `WAIT` |
| `SENDING` | 送信中 | `WAIT` |
| `SENT` かつ `sentVia == "folder"` | PCに未着（端末に保存済み） | `WAIT` |
| `SENT` かつ `sentVia == "http"` | PCに到着 | `OK` |
| `SENT` かつ `sentVia == "usb"` | PCに到着（USB） | `OK` |
| `SENT` かつ上記以外 | 送信済み | `OK` |
| `FAILED` | 送信失敗 | `FAIL` |
| （送信状況画面だけ）PC が未着と返した写真（`pcMissingFileNames` に入っている `SENT`） | PCに未着 | `WARN` |

**点検1件の札**（関数 `inspectionBadge`。4.3節）

| 点検の状態 | 札の文字 | 種類 |
|---|---|---|
| `IN_PROGRESS` | 作業中 | `WAIT` |
| `WAITING` | 送信待ち | `WAIT` |
| `SENDING` | 送信中 | `WAIT` |
| `SENT_INCOMPLETE` | 未着あり N枚 | `WARN` |
| `SENT` かつ未撮影・重複・機器IDなしがどれも0 | 送信済み | `OK` |
| `SENT` かつ上のどれかが1以上 | 送信済み（要確認あり） | `NEUTRAL` |

**点検1件の追加の札**（関数 `extraBadges`。`IN_PROGRESS` のときは出さない。撮影の途中は「抜け」ではないため）

| 条件 | 札の文字 | 種類 |
|---|---|---|
| 未撮影の機器が1台以上（ルートありの点検） | 未撮影 N台 | `MISSING` |
| 重複の機器が1台以上 | 重複 N台 | `WARN` |
| 機器IDなしの写真が1枚以上 | 機器IDなし N枚 | `WARN` |
| ルート外の機器が1台以上 | ルート外 N台 | `NEUTRAL` |

**カード左端の種類**（関数 `edgeKindOf`）: 点検の札と追加の札の種類から、`MISSING → FAIL → WARN → WAIT → NEUTRAL → OK` の順で最初に見つかったものを使う（React版の優先順「未撮影→失敗→要確認→途中→正常」に中立を足した）。

---

## 4. 共通部品（新しいファイル）

### 4.1 `ui/theme/GaugeTheme.kt`（PR1）

ファイル全体（このとおりに書く）:

```kotlin
package jp.sotuken.metercapture.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** 計器盤の色。値の正本は tasks/design/Android-計器盤デザイン.md の3.1節。画面のコードに Color(0x…) を直書きしない。 */
object GaugeColors {
    val Panel = Color(0xFFE3E6E4)
    val PanelDeep = Color(0xFFD7DCDA)
    val Dial = Color(0xFFF8F8F5)
    val Text = Color(0xFF1C2226)
    val Ink = Color(0xFF1D3A63)
    val InkTint = Color(0xFFD9E1EC)
    val Steel = Color(0xFF475158)
    val Rule = Color(0xFF757F85)
    val Hairline = Color(0xFFB4BBBE)
    val Ok = Color(0xFF2C6A45)
    val OkTint = Color(0xFFDDEBE1)
    val Warn = Color(0xFF845A00)
    val WarnTint = Color(0xFFF4E7C6)
    val Fail = Color(0xFFA23B24)
    val FailTint = Color(0xFFF5DCD5)
    val OnInk = Color(0xFFFFFFFF)
}

private val GaugeColorScheme = lightColorScheme(
    primary = GaugeColors.Ink, onPrimary = GaugeColors.OnInk,
    primaryContainer = GaugeColors.InkTint, onPrimaryContainer = GaugeColors.Ink,
    inversePrimary = GaugeColors.InkTint,
    secondary = GaugeColors.Steel, onSecondary = GaugeColors.OnInk,
    secondaryContainer = GaugeColors.PanelDeep, onSecondaryContainer = GaugeColors.Text,
    tertiary = GaugeColors.Warn, onTertiary = GaugeColors.OnInk,
    tertiaryContainer = GaugeColors.WarnTint, onTertiaryContainer = GaugeColors.Warn,
    background = GaugeColors.Panel, onBackground = GaugeColors.Text,
    surface = GaugeColors.Dial, onSurface = GaugeColors.Text,
    surfaceVariant = GaugeColors.PanelDeep, onSurfaceVariant = GaugeColors.Steel,
    surfaceTint = GaugeColors.Dial,
    inverseSurface = GaugeColors.Text, inverseOnSurface = GaugeColors.Dial,
    error = GaugeColors.Fail, onError = GaugeColors.OnInk,
    errorContainer = GaugeColors.FailTint, onErrorContainer = GaugeColors.Fail,
    outline = GaugeColors.Rule, outlineVariant = GaugeColors.Hairline,
    scrim = Color(0xFF000000),
    surfaceBright = GaugeColors.Dial, surfaceDim = GaugeColors.PanelDeep,
    surfaceContainerLowest = GaugeColors.Dial, surfaceContainerLow = GaugeColors.Dial,
    surfaceContainer = GaugeColors.Dial, surfaceContainerHigh = GaugeColors.Dial,
    surfaceContainerHighest = GaugeColors.PanelDeep,
)

/** 端末の標準書体を使う。PR7の書体同梱は当面しない。 */
val GaugeFont: FontFamily = FontFamily.Default

private fun style(size: Int, line: Int, weight: FontWeight) =
    TextStyle(fontFamily = GaugeFont, fontSize = size.sp, lineHeight = line.sp, fontWeight = weight, letterSpacing = 0.sp)

private val GaugeTypography = Typography(
    displayLarge = style(44, 44, FontWeight.Bold), displayMedium = style(44, 44, FontWeight.Bold), displaySmall = style(44, 44, FontWeight.Bold),
    headlineLarge = style(28, 36, FontWeight.Bold), headlineMedium = style(28, 36, FontWeight.Bold), headlineSmall = style(28, 36, FontWeight.Bold),
    titleLarge = style(20, 28, FontWeight.Bold), titleMedium = style(18, 26, FontWeight.Bold), titleSmall = style(16, 24, FontWeight.Bold),
    bodyLarge = style(16, 26, FontWeight.Normal), bodyMedium = style(16, 26, FontWeight.Normal), bodySmall = style(16, 26, FontWeight.Normal),
    labelLarge = style(16, 24, FontWeight.Bold), labelMedium = style(16, 24, FontWeight.Bold), labelSmall = style(14, 20, FontWeight.Medium),
)

private val GaugeShapes = Shapes(
    extraSmall = RoundedCornerShape(3.dp), small = RoundedCornerShape(4.dp), medium = RoundedCornerShape(6.dp),
    large = RoundedCornerShape(6.dp), extraLarge = RoundedCornerShape(6.dp),
)

/** 数値の桁幅をそろえる（日時・ID・枚数・台数）。 */
fun TextStyle.gaugeNum(): TextStyle = copy(fontFeatureSettings = "tnum")

/** アプリ全体のテーマ。ライト固定（端末のダークモード・壁紙の色は使わない）。 */
@Composable
fun GaugeTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = GaugeColorScheme, typography = GaugeTypography, shapes = GaugeShapes, content = content)
}
```

### 4.2 `ui/components/`（PR2）

#### `ui/components/GaugeKind.kt`（Compose を import しない。単体テストから使うため）

```kotlin
package jp.sotuken.metercapture.ui.components

/** 状態の種類。設計書3.6節。 */
enum class GaugeKind { OK, WARN, FAIL, MISSING, WAIT, NEUTRAL }

/** 札1枚ぶんの中身。 */
data class BadgeSpec(val kind: GaugeKind, val label: String)

/** カード左端に使う種類。MISSING → FAIL → WARN → WAIT → NEUTRAL → OK の順で最初に見つかったもの。空なら NEUTRAL。 */
fun edgeKindOf(kinds: Collection<GaugeKind>): GaugeKind =
    listOf(GaugeKind.MISSING, GaugeKind.FAIL, GaugeKind.WARN, GaugeKind.WAIT, GaugeKind.NEUTRAL, GaugeKind.OK)
        .firstOrNull { it in kinds } ?: GaugeKind.NEUTRAL
```

#### `ui/components/GaugeDraw.kt`（破線の枠とカード左端の描き方）

```kotlin
package jp.sotuken.metercapture.ui.components

import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.theme.GaugeColors

/** 内側に引く破線の枠（線6dp・間4dp）。未撮影のカードと札に使う。 */
fun Modifier.dashedOutline(color: Color, width: Dp, radius: Dp): Modifier = drawWithContent {
    drawContent()
    val w = width.toPx()
    drawRoundRect(
        color, topLeft = Offset(w / 2, w / 2), size = Size(size.width - w, size.height - w),
        cornerRadius = CornerRadius(radius.toPx()),
        style = Stroke(w, pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx()))),
    )
}

/** カード左端の帯（幅10dp）。設計書3.6節の表のとおり。 */
fun DrawScope.drawGaugeEdge(kind: GaugeKind) {
    val e = 10.dp.toPx()
    val h = size.height
    when (kind) {
        GaugeKind.OK -> drawRect(GaugeColors.Ok, size = Size(4.dp.toPx(), h))
        GaugeKind.WAIT, GaugeKind.NEUTRAL -> drawRect(GaugeColors.Hairline, size = Size(4.dp.toPx(), h))
        GaugeKind.FAIL -> drawRect(GaugeColors.Fail, size = Size(e, h))
        GaugeKind.WARN -> clipRect(0f, 0f, e, h) {
            drawRect(GaugeColors.WarnTint, size = Size(e, h))
            val step = 14.dp.toPx()
            var x = -h
            while (x < e) {
                drawLine(GaugeColors.Warn, Offset(x, h), Offset(x + h, 0f), strokeWidth = 6.dp.toPx())
                x += step
            }
        }
        GaugeKind.MISSING -> Unit
    }
}
```

#### `ui/components/StatusBadge.kt`

- `@Composable fun StatusShape(kind: GaugeKind, color: Color, modifier: Modifier = Modifier)`: `Canvas(modifier)` で形を描く。`r = size.minDimension / 2`、中心 `center`。
  - `OK`: `drawCircle(color, r * 0.8f, center)`
  - `WARN`: `Path` で三角を描いて塗る（点は `(0.5w, 0.1h)`、`(0.95w, 0.9h)`、`(0.05w, 0.9h)`）
  - `FAIL`: `drawRect(color, topLeft = Offset(0.15w, 0.15h), size = Size(0.7w, 0.7h))`
  - `MISSING`: `drawCircle(color, r * 0.8f, center, style = Stroke(2.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 2.dp.toPx()))))`
  - `WAIT`: `drawCircle(color, r * 0.84f, center, style = Stroke(1.5.dp.toPx()))` のあとに `drawCircle(color, r * 0.32f, center)`
  - `NEUTRAL`: `drawCircle(color, r * 0.8f, center, style = Stroke(1.5.dp.toPx()))`
- `@Composable fun StatusBadge(kind: GaugeKind, label: String, modifier: Modifier = Modifier)`:
  - 地と文字の色:
    - `OK` → (`OkTint`, `Ok`)
    - `WARN` → (`Warn`, `OnInk`)
    - `FAIL` → (`Fail`, `OnInk`)
    - `MISSING` → (`Dial`, `Ink`)
    - `WAIT` → (`Dial`, `Steel`)
    - `NEUTRAL` → (`Dial`, `Ink`)
  - 枠: `OK` → `BorderStroke(1.dp, Ok)`、`WAIT` → `BorderStroke(1.dp, Rule)`、`NEUTRAL` → `BorderStroke(1.dp, Ink)`、ほかは `null`。`MISSING` は `border = null` にし、`modifier` に `.dashedOutline(GaugeColors.Ink, 2.dp, 4.dp)` を足す。
  - 中身: `Surface(color = 地, contentColor = 文字, shape = MaterialTheme.shapes.small, border = 枠, modifier = modifier.heightIn(min = 32.dp)…)`
  - その中に `Row(Modifier.padding(horizontal = 10.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp))`
  - `Row` の中は `StatusShape(kind, 文字の色, Modifier.size(18.dp))` と `Text(label, style = MaterialTheme.typography.labelLarge, color = 文字の色)`
- `@Composable fun BadgeRow(badges: List<BadgeSpec>, modifier: Modifier = Modifier)`: `FlowRow(modifier, horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp))` で `badges` を `StatusBadge` で並べる。`FlowRow` に実験的APIの警告が出たら、関数に `@OptIn(ExperimentalLayoutApi::class)` を付ける。

#### `ui/components/GaugeCard.kt`

```kotlin
@Composable
fun GaugeCard(
    kind: GaugeKind?,                       // null = 左端の帯なし（ふつうのカード）
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    enabled: Boolean = true,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = MaterialTheme.shapes.medium
    val missing = kind == GaugeKind.MISSING
    val border = if (missing) null else BorderStroke(1.dp, GaugeColors.Hairline)
    val outer = if (missing) modifier.dashedOutline(GaugeColors.Ink, 2.dp, 6.dp) else modifier
    val body: @Composable () -> Unit = {
        Column(
            Modifier.fillMaxWidth()
                .drawBehind { if (kind != null) drawGaugeEdge(kind) }
                .padding(start = if (kind != null && !missing) 26.dp else 16.dp, end = 16.dp, top = 16.dp, bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            content = content,
        )
    }
    if (onClick != null) {
        Surface(onClick = onClick, enabled = enabled, modifier = outer, shape = shape,
            color = GaugeColors.Dial, contentColor = GaugeColors.Text, border = border, content = body)
    } else {
        Surface(modifier = outer, shape = shape, color = GaugeColors.Dial, contentColor = GaugeColors.Text, border = border, content = body)
    }
}
```

#### `ui/components/GaugeButtons.kt`

```kotlin
@Composable
fun GaugePrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    Button(onClick = onClick, modifier = modifier.heightIn(min = 48.dp), enabled = enabled, shape = MaterialTheme.shapes.small) {
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

@Composable
fun GaugeSecondaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    OutlinedButton(
        onClick = onClick, modifier = modifier.heightIn(min = 48.dp), enabled = enabled, shape = MaterialTheme.shapes.small,
        border = BorderStroke(1.dp, if (enabled) GaugeColors.Ink else GaugeColors.Hairline),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = GaugeColors.Dial, contentColor = GaugeColors.Ink),
    ) { Text(text, style = MaterialTheme.typography.labelLarge) }
}

/** 削除のような取り消せない操作の文字ボタン。文字色を赤錆にする。 */
@Composable
fun GaugeDangerTextButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    TextButton(onClick = onClick, modifier = modifier, enabled = enabled,
        colors = ButtonDefaults.textButtonColors(contentColor = GaugeColors.Fail)) { Text(text, style = MaterialTheme.typography.labelLarge) }
}
```

#### `ui/components/TickRule.kt`（見出しの下の目盛りの定規。計器の意匠はここだけ）

```kotlin
@Composable
fun TickRule(modifier: Modifier = Modifier) {
    Canvas(modifier.fillMaxWidth().height(10.dp)) {
        drawRect(GaugeColors.Ink, size = Size(size.width, 2.dp.toPx()))
        val step = 12.dp.toPx()
        var x = 0f
        var i = 0
        while (x <= size.width) {
            val major = i % 5 == 0                       // 60dp ごとに大目盛り
            drawRect(GaugeColors.Ink, topLeft = Offset(x, 0f),
                size = Size((if (major) 2 else 1).dp.toPx(), (if (major) 10 else 5).dp.toPx()))
            x += step
            i++
        }
    }
}
```

### 4.3 判定の関数（`ui/` の中の純粋な関数。単体テストで確かめる）

#### `ui/QueueDisplay.kt` に足す・書き換える（PR3・PR4）

```kotlin
/** 写真の送信状態の種類（設計書3.6節）。判定の順は sendStatusLabel と同じ。 */
internal fun sendStatusKind(item: QueueItem, currentReceiverId: String? = null, isSendable: (QueueItem) -> Boolean = { true }): GaugeKind = when {
    item.isHeldFor(currentReceiverId) -> GaugeKind.WARN
    !isSendable(item) -> GaugeKind.WAIT
    else -> when (item.sendState) {
        SendState.PENDING, SendState.SENDING -> GaugeKind.WAIT
        SendState.SENT -> if (item.sentVia == QueueItem.VIA_FOLDER) GaugeKind.WAIT else GaugeKind.OK
        SendState.FAILED -> GaugeKind.FAIL
    }
}

/** 保存されている lastError（生の文）を、画面に出す理由の言葉（設計書5.2節の9語）に置き換える。空なら null。 */
internal fun reasonFromLastError(lastError: String?): String? {
    val text = lastError?.trim()?.takeIf { it.isNotEmpty() } ?: return null
    fun after(prefixes: List<String>): String? = prefixes.firstOrNull { text.startsWith(it) }?.let { text.removePrefix(it).trim() }
    // 詳細がすでに理由の言葉なら、そのまま使う（例「PC未接続: 接続できません」。QueueSendWorker.kt:67 が作る。
    // classifyFailureMessage は英語の手がかりしか見ないので、渡すと「応答がありません」に化ける）
    val known = setOf("接続できません", "合言葉が違います", "送信先の形式が違います", "応答がありません")
    fun classify(detail: String) = if (detail in known) detail else classifyFailureMessage(detail)
    if (text.startsWith("送信先未設定")) return "送信先が未設定です"
    after(listOf("PC未接続:", "PC未接続："))?.let { return classify(it) }
    after(listOf("HTTP失敗:", "追い送り失敗:"))?.let { detail ->
        return when {
            detail.contains("Image file does not exist") -> "写真のファイルが見つかりません"
            listOf("HTTP 400", "HTTP 409", "HTTP 413").any { detail.contains(it) } -> "PCが写真を受け付けませんでした"
            else -> classify(detail)
        }
    }
    return "端末への保存に失敗しました"
}

/** 行に出す未着の理由。FAILED と、送信箱に保存しただけ（SENT＋folder）の写真だけが対象。 */
internal fun undeliveredReason(item: QueueItem): String? =
    if (item.sendState == SendState.FAILED || isUndelivered(item)) reasonFromLastError(item.lastError) else null
```

`errorTextFor` は、条件の判定（保留なら null、送信対象外なら null、`connectionUnreachable` の扱い）を今のまま残し、返す文だけを次のように変える。

```kotlin
    if (item.sendState == SendState.FAILED || isUndelivered(item)) return reasonFromLastError(item.lastError)
    if (item.sendState == SendState.PENDING && connectionUnreachable) {
        return reasonFromLastError(item.lastError)
            ?: connectionReason?.takeIf { it.isNotBlank() }
            ?: "接続できません"
    }
    return null
```

#### `ui/inspection/InspectionDisplay.kt` に足す（PR5。PR6 でも使う）

```kotlin
/** 点検1件の札（設計書3.6節）。 */
fun inspectionBadge(state: InspectionState, summary: InspectionSummary, undelivered: Int): BadgeSpec = when (state) {
    InspectionState.IN_PROGRESS -> BadgeSpec(GaugeKind.WAIT, "作業中")
    InspectionState.WAITING -> BadgeSpec(GaugeKind.WAIT, "送信待ち")
    InspectionState.SENDING -> BadgeSpec(GaugeKind.WAIT, "送信中")
    InspectionState.SENT_INCOMPLETE -> BadgeSpec(GaugeKind.WARN, "未着あり ${undelivered}枚")
    InspectionState.SENT ->
        if (summary.missing.isEmpty() && summary.duplicates.isEmpty() && summary.unidentifiedCount == 0) BadgeSpec(GaugeKind.OK, "送信済み")
        else BadgeSpec(GaugeKind.NEUTRAL, "送信済み（要確認あり）")
}

/** 点検1件の追加の札。作業中は出さない。 */
fun extraBadges(state: InspectionState, summary: InspectionSummary): List<BadgeSpec> =
    if (state == InspectionState.IN_PROGRESS) emptyList() else buildList {
        if (summary.missing.isNotEmpty()) add(BadgeSpec(GaugeKind.MISSING, "未撮影 ${summary.missing.size}台"))
        if (summary.duplicates.isNotEmpty()) add(BadgeSpec(GaugeKind.WARN, "重複 ${summary.duplicates.size}台"))
        if (summary.unidentifiedCount > 0) add(BadgeSpec(GaugeKind.WARN, "機器IDなし ${summary.unidentifiedCount}枚"))
        if (summary.extra.isNotEmpty()) add(BadgeSpec(GaugeKind.NEUTRAL, "ルート外 ${summary.extra.size}台"))
    }

/** 一覧のカードに出す開始日時。例「11/12(木) 09:00」。読めない値はそのまま返す。 */
fun formatStartedLabel(startedAt: String, zone: ZoneId = ZoneId.systemDefault()): String =
    runCatching { DateTimeFormatter.ofPattern("M/d(E) HH:mm", Locale.JAPAN).withZone(zone).format(Instant.parse(startedAt)) }.getOrDefault(startedAt)
```

`inspectionStateLabel` は残す（撮影画面の見出しで使っている）。文言の変更は5.1節の表のとおり。

---

## 5. 機能追加 (b): 未着理由の文言をそろえる

### 5.1 `ui/` の中の文字列（ソースを書き換える。PR3）

行番号は `origin/main` `5c7be01` の時点のもの。

| # | ファイル:行 | 今の文言 | 新しい文言 |
|---|---|---|---|
| 1 | `ui/ConnectionStatus.kt:81` | `▲ 送信先が未設定です（タップして設定）` | `■ 送信先が未設定です（タップして設定）` |
| 2 | `ui/ConnectionStatus.kt:82` | `… PCとの接続を確認中` | `◎ PCとの接続を確認中` |
| 3 | `ui/ConnectionStatus.kt:83` | `● PCに接続中　未着 ${undelivered}件　最終送信 $lastSent` | `● PCに接続中　未着 ${undelivered}枚`。`lastSent` が空白でないときだけ、後ろに `　最終送信 $lastSent` を付ける（今は点検画面から `""` が渡り、「最終送信 」だけが残っている） |
| 4 | `ui/ConnectionStatus.kt:85` | `（送信箱に保存中）` | `（端末に保存中）`（`（送信待ち）` は変えない） |
| 5 | `ui/ConnectionStatus.kt:86` | `○ PCに届かない${savingLabel}　未着 ${undelivered}件　$reason` | `▲ PCにつながりません${savingLabel}　未着 ${undelivered}枚　$reason` |
| 6 | `ui/ConnectionStatus.kt:95` | `届かない（$reason）` | `つながりません（$reason）` |
| 7 | `ui/QueueDisplay.kt:14` | `別のPC宛て(保留)` | `別のPC宛て（保留）` |
| 8 | `ui/QueueDisplay.kt:16` | `点検中(完了すると送信します)` | `完了後に送信` |
| 9 | `ui/QueueDisplay.kt:21` | `PC未到着・端末に保存済み` | `PCに未着（端末に保存済み）` |
| 10 | `ui/QueueDisplay.kt:22` | `PC受信済み` | `PCに到着` |
| 11 | `ui/QueueDisplay.kt:23` | `送信済み(USB)` | `PCに到着（USB）` |
| 12 | `ui/QueueDisplay.kt:26` | `失敗` | `送信失敗` |
| 13 | `ui/QueueDisplay.kt:47` | `未送信: ${total}件（端末に保存済み）` | `未送信 ${total}枚（端末に保存済み）` |
| 14 | `ui/QueueDisplay.kt:49` | `PC未到着: ${total}件（端末に保存済み）` | `PCに未着 ${total}枚（端末に保存済み）` |
| 15 | `ui/QueueDisplay.kt:54-81` | `errorTextFor` が生の `lastError` か `PCに届いていません。…` を返す | 4.3節のとおり、5.2節の理由の言葉を返す |
| 16 | `ui/QueueDisplay.kt:95` | `端末内の写真を削除します。PCに届いた記録は消えません。` | `端末内の写真を削除します。PCに到着した記録は消えません。` |
| 17 | `ui/QueueDisplay.kt:97` | `この写真を削除します。まだPCに届いていないため、削除するとPCには送られません。` | `この写真を削除します。まだPCに未着のため、削除するとPCには送られません。` |
| 18 | `ui/QueueListScreen.kt:380`（`stateLabel` の `FAILED`） | `失敗` | `送信失敗` |
| 19 | `ui/QueueListScreen.kt:211` 付近（`errorTextFor` の結果を出している `Text`） | 結果をそのまま表示 | `"理由：$it"` と表示 |
| 20 | `ui/QueueListScreen.kt:386`（`stateColor` の `SENDING`） | `colorScheme.tertiary` | `colorScheme.onSurfaceVariant`（`tertiary` が黄土になり、送信中が警告に見えるため） |
| 21 | `ui/MeterCaptureApp.kt:283` | `未着: ${undelivered}件` | `未着 ${undelivered}枚` |
| 22 | `ui/PairingScreen.kt:107` | `PC未到着の写真が${pendingCount}件あります。既存の写真も新しいPCへ送ります。` | `PCに未着の写真が${pendingCount}枚あります。既存の写真も新しいPCへ送ります。` |
| 23 | `ui/inspection/InspectionDisplay.kt:28` | `写真${…photoCount}枚 ・ ${…deviceCount}機器` | `写真${…photoCount}枚 ・ ${…deviceCount}台` |
| 24 | `ui/inspection/InspectionDisplay.kt:32` | `対象 ${routeDeviceCount}機器中 ${shotRouteDeviceCount}機器を撮影` | `撮影 ${shotRouteDeviceCount}/${routeDeviceCount}台` |
| 25 | `ui/inspection/InspectionDisplay.kt:61` | `${deviceCount}機器`／`${shot} / ${route}機器` | `${deviceCount}台`／`撮影 ${shot}/${route}台` |
| 26 | `ui/inspection/InspectionDisplay.kt:72` | `対象一覧がないため、未撮影の機器は判定できません` | `ルートがないため、未撮影の機器は判定できません` |
| 27 | `ui/inspection/InspectionDisplay.kt:80` | `一覧外：$it` | `ルート外：$it` |
| 28 | `ui/inspection/InspectionDisplay.kt:82` | `対象一覧がないため、未撮影は確認できません` | `ルートがないため、未撮影は確認できません` |
| 29 | `ui/inspection/InspectionDisplay.kt:98` | `送信済み（未到着${undeliveredCount}枚）` | `未着あり ${undeliveredCount}枚` |
| 30 | `ui/inspection/InspectionDisplay.kt:116` | `…写真${count}枚 ・ ${devices}機器` | `…写真${count}枚 ・ ${devices}台` |
| 31 | `ui/inspection/InspectionDisplay.kt:118` | `写真${count}枚 ・ ${delivered} / ${count}枚到着` | `写真${count}枚 ・ 到着 ${delivered}/${count}枚` |
| 32 | `ui/inspection/InspectionDisplay.kt:119` | `写真${count}枚 ・ すべてPCへ到着` | `写真${count}枚 ・ すべてPCに到着` |
| 33 | `ui/inspection/InspectionDisplay.kt:120` | `写真${count}枚 ・ ${undelivered}枚が未到着` | `写真${count}枚 ・ 未着 ${undelivered}枚` |
| 34 | `ui/inspection/InspectionDisplay.kt:123` | `対象${route}機器のうち${shot}機器を撮影` | `撮影 ${shot}/${route}台` |
| 35 | `ui/inspection/InspectionDisplay.kt:131` | `点検なしの写真: 未着${legacy}件` | `点検なしの写真 未着 ${legacy}枚` |
| 36 | `ui/inspection/InspectionSendStatusScreen.kt:46` | `送信済み（一部失敗あり）` | `未着あり ${undelivered}枚` |
| 37 | `ui/inspection/InspectionSendStatusScreen.kt:51` | `すべてPCに届きました` | `すべてPCに到着しました` |
| 38 | `ui/inspection/InspectionSendStatusScreen.kt:52` | `${undelivered}枚が届いていません` | `${undelivered}枚がPCに未着です` |
| 39 | `ui/inspection/InspectionSendStatusScreen.kt:61` | `… 写真${photos.size}枚 ・ ${summary.deviceCount}機器` | `… 写真${photos.size}枚 ・ ${summary.deviceCount}台` |
| 40 | `ui/inspection/InspectionSendStatusScreen.kt:62` | `写真 $arrived / ${photos.size}枚 到着`（SENT）と `$arrived / ${photos.size}枚`（それ以外） | どちらも `到着 $arrived/${photos.size}枚` |
| 41 | `ui/inspection/InspectionSendStatusScreen.kt:65` | `写真の一覧：送れませんでした（${manifestError}）` | 5.2節の表 M1・M2 のとおり |
| 42 | `ui/inspection/InspectionSendStatusScreen.kt:66` | `写真の一覧：未送信 残りの写真が届いたら送ります。` | `写真の一覧：未送信（写真がすべて到着したら送ります）` |
| 43 | `ui/inspection/InspectionSendStatusScreen.kt:72` | `…には接続していますが、PCに届きません。PCの受信アプリと接続を確認してください。` | `…には接続していますが、PCにつながりません。PCの受信アプリと接続を確認してください。` |
| 44 | `ui/inspection/InspectionSendStatusScreen.kt:76` | `PC未到着` | `PCに未着`（理由は5.2節 R9） |
| 45 | `ui/inspection/InspectionSendStatusScreen.kt:106` | `届いていない写真を再送` | `未着の写真を再送` |
| 46 | `ui/inspection/ConnectionGuideScreen.kt:18` | `3. PCの受信アプリを開く。接続表示が「PCに届きます」になるまで待つ。` | `3. PCの受信アプリを開く。画面上の帯が「PCに接続中」になるまで待つ。` |
| 47 | `ui/inspection/ConnectionGuideScreen.kt:20` | `PCに届きます`／`PCに届きません`／`未確認` | `PCに接続中`／`PCにつながりません`／`確認中` |
| 48 | `ui/inspection/InspectionCreateScreen.kt:41` | `対象一覧がないため、未撮影の機器は判定できません` | `ルートがないため、未撮影の機器は判定できません` |
| 49 | `ui/inspection/RouteListScreen.kt:16` | `${…devices.size}機器 ・ …` | `${…devices.size}台 ・ …` |
| 50 | `ui/inspection/RouteListScreen.kt:39` | `${row.count}機器 ・ ${row.updatedAt}` | `${row.count}台 ・ ${row.updatedAt}` |
| 51 | `ui/inspection/InspectionApp.kt:148` | `${it.route.name}（${it.route.devices.size}機器）` | `${it.route.name}（${it.route.devices.size}台）` |
| 52 | `ui/inspection/InspectionApp.kt:307` | `${route.devices.size}機器` | `${route.devices.size}台` |

変えない文言（理由付き）:
- `機器IDなし`・`機器名なし`・`機器が選ばれていません`: 単位ではなく名詞のため
- `送信中のため削除できません`、`再送の準備に失敗しました: …`: 送信状態や未着を表す言葉ではないため

### 5.2 生のエラー文（`ui/` の外で作り、DBに保存される。ソースは変えず、表示するときに置き換える）

`queue/`・`inspection/` の文は変えない（ロジックに触れないため。既存テスト `InspectionSendCoordinatorTest`・`SendRouterTest`・`RoomQueueStoreTest` もそのまま）。置き換えは `reasonFromLastError`（4.3節）と `buildSendStatusUiState` の中だけで行う。

| # | 生の値（作る場所） | 画面に出す理由の言葉 |
|---|---|---|
| R1 | `null` か空白 | 出さない（「理由：」の行ごと出さない） |
| R2 | `送信先未設定`（`queue/SendRouter.kt:38`） | `送信先が未設定です` |
| R3 | `PC未接続: <詳細>`（`queue/SendRouter.kt:43`） | 詳細が下の4語のどれかなら、その語をそのまま使う（例: `PC未接続: 接続できません` → `接続できません`。`queue/QueueSendWorker.kt:67` が作る、いちばん多い形）。それ以外は `classifyFailureMessage(<詳細>)` の結果。どちらにしても次の4つのどれかになる: `接続できません`／`合言葉が違います`／`送信先の形式が違います`／`応答がありません` |
| R4 | `HTTP失敗: <詳細>`（`queue/SendRouter.kt:77`）・`追い送り失敗: <詳細>`（`:123`）で、詳細に `Image file does not exist` を含む（`queue/sender/HttpSender.kt:32`） | `写真のファイルが見つかりません` |
| R5 | 同じく、詳細に `HTTP 400`・`HTTP 409`・`HTTP 413` を含む（`HttpSender.kt` の Upload／Manifest failed） | `PCが写真を受け付けませんでした` |
| R6 | 同じく、上の2つ以外 | R3 と同じ扱い（詳細が4語のどれかならそのまま、それ以外は `classifyFailureMessage(<詳細>)`） |
| R7 | 上のどれでもない（`queue/SendRouter.kt:96-97` の送信箱への保存失敗 `Folder sender failed` や、例外の英文） | `端末への保存に失敗しました` |
| R8 | 送信待ちで、PCにつながらない未送信の写真（`errorTextFor` の `PENDING` の分岐） | `reasonFromLastError(lastError)` が null なら、接続の理由（`health.reason`。すでに `classifyFailureMessage` 済み）。それも空なら `接続できません` |
| R9 | PC が未着と返した写真（`inspection.pcMissingFileNames` に入っている `SENT`） | `PCで写真が見つかりません` |
| M1 | `manifestError` が `PCに届かないため、写真の一覧を送れませんでした`（`inspection/InspectionSendCoordinator.kt:43`） | 写真の一覧の行を `写真の一覧：未送信（PCにつながりません）` にする |
| M2 | `manifestError` がそれ以外 | 今のまま `写真の一覧：送れませんでした（${manifestError}）` |

理由の言葉は次の9語に限る:
- 送信先が未設定です
- 接続できません
- 合言葉が違います
- 送信先の形式が違います
- 応答がありません
- 写真のファイルが見つかりません
- PCが写真を受け付けませんでした
- 端末への保存に失敗しました
- PCで写真が見つかりません

画面では、どれも1行で `理由：{言葉}`（`bodyMedium`、色 `Text`）と出す。

### 5.3 送信状況画面の行に理由を出す（SKくんの指摘「行ごとの未着理由が出ない」への対応。PR3）

- `SendRow`（`ui/inspection/InspectionSendStatusScreen.kt:19`）の最後に、引数 `val reason: String? = null` を足す。
- `buildSendStatusUiState` の中で、行ごとに次の値を入れる。
  - `pcMissingFileNames` に入っていて、かつ `SENT` の写真 → `"PCで写真が見つかりません"`
  - それ以外 → `undeliveredReason(photo)`
- 画面（同じファイルの `InspectionSendStatusScreen`）で、`Text(row.status)` の次に `row.reason?.let { Text("理由：$it") }` を足す。見た目は PR6 で整える。

### 5.4 既存テストで直す期待値（PR3 だけ。ここに挙げた行の、文字列の期待値だけを直す）

| テストのファイル:行 | 今の期待値 | 新しい期待値 |
|---|---|---|
| `ui/QueueDisplayTest.kt:14` | `この写真を削除します。まだPCに届いていないため、削除するとPCには送られません。` | `この写真を削除します。まだPCに未着のため、削除するとPCには送られません。` |
| `ui/QueueDisplayTest.kt:49`・`:106` | `PC未到着・端末に保存済み` | `PCに未着（端末に保存済み）` |
| `ui/QueueDisplayTest.kt:54`・`:107` | `PC受信済み` | `PCに到着` |
| `ui/QueueDisplayTest.kt:66`・`:108` | `失敗` | `送信失敗` |
| `ui/QueueDisplayTest.kt:78`・`:142` | `PC未到着: N件（端末に保存済み）` | `PCに未着 N枚（端末に保存済み）`（Nは今の数のまま） |
| `ui/QueueDisplayTest.kt:89`・`:90` | `接続失敗` | `端末への保存に失敗しました`（R7） |
| `ui/QueueDisplayTest.kt:109` | `点検中(完了すると送信します)` | `完了後に送信` |
| `ui/QueueDisplayTest.kt:111` | `別のPC宛て(保留)` | `別のPC宛て（保留）` |
| `ui/QueueDisplayTest.kt:120`・`:126`・`:133` | `未送信: N件（端末に保存済み）` | `未送信 N枚（端末に保存済み）` |
| `ui/QueueDisplayTest.kt:151`・`:155` | `PCに届いていません。接続できません` | `接続できません` |
| `queue/ReceiverPinTest.kt:104` | `別のPC宛て(保留)` | `別のPC宛て（保留）`（`ui/` の関数を確かめている行。文字列だけ直す） |
| `ui/ConnectionStatusTest.kt:124` | `● PCに接続中　未着 3件　最終送信 12:34` | `● PCに接続中　未着 3枚　最終送信 12:34` |
| `ui/ConnectionStatusTest.kt:128`・`:160` | `○ PCに届かない（送信箱に保存中）　未着 2件　接続できません` | `▲ PCにつながりません（端末に保存中）　未着 2枚　接続できません` |
| `ui/ConnectionStatusTest.kt:139` | `届かない（接続できません）` | `つながりません（接続できません）` |
| `ui/ConnectionStatusTest.kt:164` | `○ PCに届かない（送信待ち）　未着 2件　接続できません` | `▲ PCにつながりません（送信待ち）　未着 2枚　接続できません` |
| `ui/ConnectionStatusTest.kt`・`ui/NetworkStatusTest.kt` の、ほかの行で `▲ 送信先が未設定です` を期待している所 | `▲ 送信先が未設定です（タップして設定）` | `■ 送信先が未設定です（タップして設定）` |
| 同じく `… PCとの接続を確認中` を期待している所 | `… PCとの接続を確認中` | `◎ PCとの接続を確認中` |
| 同じく `○ PCに届かない` や `未着 N件` を含む所 | 5.1節 #3〜#5 の旧文言 | 5.1節 #3〜#5 の新文言 |
| `ui/inspection/HomeUiStateTest.kt:18` | `大久保 ・ 第1工場 写真3枚 ・ 2機器` | `大久保 ・ 第1工場 写真3枚 ・ 2台` |
| `ui/inspection/HomeUiStateTest.kt:23` | `送信済み（未到着1枚）`、`写真3枚 ・ 1枚が未到着` | `未着あり 1枚`、`写真3枚 ・ 未着 1枚` |
| `ui/inspection/HomeUiStateTest.kt:27` | `点検なしの写真: 未着1件` | `点検なしの写真 未着 1枚` |
| `ui/inspection/CaptureUiStateTest.kt:15` | `対象 2機器中 1機器を撮影` | `撮影 1/2台` |
| `ui/inspection/CaptureUiStateTest.kt:18` | `写真2枚 ・ 1機器` | `写真2枚 ・ 1台` |
| `ui/inspection/CaptureUiStateTest.kt:19` | `この点検：写真2枚 ・ 1機器` | `この点検：写真2枚 ・ 1台` |
| `ui/inspection/HistoryUiStateTest.kt:12` | `1 / 2機器` | `撮影 1/2台` |
| `ui/inspection/HistoryUiStateTest.kt:24` | `対象一覧がないため、未撮影の機器は判定できません` | `ルートがないため、未撮影の機器は判定できません` |
| `ui/inspection/RouteListUiStateTest.kt:12` | `1機器 ・ ${route.updatedAt} ・ QR` | `1台 ・ ${route.updatedAt} ・ QR` |
| `ui/inspection/CompleteUiStateTest.kt:10` | リスト中の `一覧外：Z-9` | `ルート外：Z-9`（ほかの3つはそのまま） |
| `ui/inspection/CompleteUiStateTest.kt:21` | `対象一覧がないため、未撮影は確認できません` | `ルートがないため、未撮影は確認できません` |
| `ui/inspection/SendStatusUiStateTest.kt:35` | `すべてPCに届きました` | `すべてPCに到着しました` |
| `ui/inspection/SendStatusUiStateTest.kt:40` | `1枚が届いていません` | `1枚がPCに未着です` |

テストのパスはどれも `android/app/src/test/kotlin/jp/sotuken/metercapture/` から。

- この表に無い期待値が落ちたら、直さずに止まって報告する。
- テストを消す・`@Ignore` を付ける・判定の `assert` を変えることはしない。

---

## 6. 画面ごとの変更（変更前 → 変更後）

全画面に共通すること:
- 画面の地は `Panel`。`Scaffold` の既定の `background` から来るので、画面ごとの指定は要らない。
- 区画の見出しは `titleLarge`、補足の文は `bodyMedium` で色 `GaugeColors.Steel`。
- 画面の中の M3 の `Card`・`OutlinedCard` は、すべて `GaugeCard` に置き換える。
- `Button` は `GaugePrimaryButton`、`OutlinedButton` は `GaugeSecondaryButton` に置き換える。
- 削除の `TextButton` は `GaugeDangerTextButton` に置き換える。
- エラー文の `Text` は `color = MaterialTheme.colorScheme.error`（`Fail`）のまま。
- 数値を含む `Text` の `style` には `.gaugeNum()` を付ける。対象は、日時・ID・「写真N枚」・「撮影 m/n台」・「到着 a/n枚」。

### 6.1 共通の枠 `InspectionScaffold`（`ui/inspection/InspectionScaffold.kt`、PR2）

- 変更前: 接続帯 → タイトル行（`headlineSmall`＋「点検一覧」）→ 中身。`Column` の `spacedBy(12.dp)`。
- 変更後（並びはこの順。`Column` の `spacedBy` はやめ、余白は下の値で付ける）:
  1. `ConnectionBar`（6.2節）
  2. タイトル行: `Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 16.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically)`
     - 左: `Text(title, style = headlineSmall, color = GaugeColors.Text)`
     - 右: `onHome != null` のときだけ `TextButton(onHome) { Text("点検一覧") }`
  3. `TickRule(Modifier.padding(horizontal = 16.dp, vertical = 8.dp))`
  4. `content()`
- 引数（署名）は変えない。

### 6.2 接続帯 `ConnectionBar`（`ui/ConnectionBar.kt`、PR2）

- 変更前: 地と文字が M3 の一般色の直書き（ピンク・灰・薄緑・黄）。`bodyMedium`、余白は左右12・上下8。
- 変更後: 色だけ変える。文字は `connectionBarText` が付ける形の記号（■ ◎ ● ▲。5.1節 #1〜#5）で区別するので、絵は描かない。
  - 未設定 `NOT_CONFIGURED`: 地 `Fail`、文字 `OnInk`
  - 確認中 `CHECKING`: 地 `PanelDeep`、文字 `Steel`
  - 接続中 `CONNECTED`: 地 `OkTint`、文字 `Ok`
  - 届かない `UNREACHABLE`: 地 `Warn`、文字 `OnInk`
  - `style = bodyLarge`、`fontWeight = FontWeight.Bold`、`maxLines = 2`、余白は左右16dp・上下12dp。タップの動作は変えない。

### 6.3 点検の一覧 `InspectionHomeScreen`（PR5）

変更前: 「新しい点検を作る」ボタン → 3つの区画（作業中／送信待ち・送信中／送信済み）。カードは札の文字（`labelLarge`）・点検名・補足・進み具合・操作ボタン → 下に接続・設定の文字ボタン。

変更後（上から）:
1. `GaugePrimaryButton("新しい点検を作る", onCreate, Modifier.fillMaxWidth())`
2. 区画ごとに、見出し `Text("$title ${cards.size}件", titleLarge)`。`title` は今の3つのまま（作業中／送信待ち・送信中／送信済み）。
   - カードが0件のとき: `Text("${title}の点検はありません", bodyMedium, color = Steel)`
3. カード1件: `GaugeCard(kind = card.edgeKind)`（カード全体は押せない）。中身は上から:
   1. `BadgeRow(listOf(BadgeSpec(card.kind, card.stateLabel)) + card.badges)`
   2. `Text(card.startedLabel, bodyMedium.gaugeNum(), color = Steel)`（例「11/12(木) 09:00」）
   3. `Text(card.title, titleMedium)`
   4. `Text(card.subtitle, bodyMedium.gaugeNum(), color = Steel)`
   5. `card.progress?.let { Text(it, titleLarge.gaugeNum(), color = Ink) }`（例「撮影 4/5台」）
   6. 操作ボタン（`Modifier.fillMaxWidth()`）: `card.target is AppScreen.Capture` なら `GaugePrimaryButton(card.action)`、それ以外は `GaugeSecondaryButton(card.action)`
4. 区画「接続と設定」: 見出し `Text("接続と設定", titleLarge)` の下に、今と同じ順で並べる。
   - `GaugeSecondaryButton("接続を確認する", fillMaxWidth)`
   - `TextButton("送信先の設定")`
   - `TextButton("ルート")`（`onRoutes != null` のとき）
   - `state.legacyUndelivered` の `TextButton`
   - `TextButton("点検なしで撮る（従来の画面）")`
- 余白: 外側は `padding(16.dp)`、要素の間は `spacedBy(12.dp)`。

`HomeCard`（`ui/inspection/InspectionDisplay.kt:13`）の最後に、次を足す（既定値付きなので既存テストはそのまま通る）:

```kotlin
val kind: GaugeKind = GaugeKind.WAIT,
val badges: List<BadgeSpec> = emptyList(),
val edgeKind: GaugeKind = GaugeKind.WAIT,
val startedLabel: String = "",
```

`buildHomeUiState` での値:
- `val badge = inspectionBadge(inspection.state, summary, undelivered)`
- `stateLabel = badge.label`
- `kind = badge.kind`
- `badges = extraBadges(inspection.state, summary)`
- `edgeKind = edgeKindOf(listOf(badge.kind) + badges.map { it.kind })`
- `startedLabel = formatStartedLabel(inspection.startedAt)`

### 6.4 新しい点検 `InspectionCreateScreen`（PR5）

- 文言は5.1節 #48 のとおり。並びは変えない。
- 冒頭の案内文: `bodyMedium`、`Steel`
- 「点検ルート」: `titleLarge`
- ルートなしの注記: `bodyMedium`、`Steel`
- 「点検を始める」: `GaugePrimaryButton`（`Modifier.fillMaxWidth()`、文字は `if (state.starting) "作成中..." else "点検を始める"`）
- 入力欄・ラジオボタンは M3 のまま（テーマで紺と罫の色になる）。

### 6.5 ルート `RouteListScreen`（PR5）

- 「保存済みのルート」: `titleLarge`
- 保存済みの行: `GaugeCard(kind = null)`。中身は `Text(row.name, titleMedium)`、`Text(row.detail, bodyMedium.gaugeNum(), Steel)`、`GaugeDangerTextButton("削除", enabled = !state.loading)`
- 「PCから取得」は `GaugePrimaryButton`、「ルートのQRを読む」は `GaugeSecondaryButton`。どちらも `fillMaxWidth`。
- 読み込み中の文: `bodyMedium`、`Steel`
- PCから取った行: `GaugeCard(kind = null, onClick = { onPick(row.routeId) }, enabled = !state.loading)`。中身は `Text(row.name, titleMedium)`、`Text("${row.count}台 ・ ${row.updatedAt}", bodyMedium.gaugeNum(), Steel)`
- ルートの保存確認のダイアログ（`InspectionApp.kt:303-317`）は、文言だけ変える（5.1節 #52）。

### 6.6 撮影 `InspectionCaptureScreen`（PR4）

変更前: 見出し → 点検名・状態 → 進み具合の文 → 未撮影の `OutlinedButton`（「未撮影：名前 ID」）→ QR → 撮影する機器のカード → カメラ → 保存後のカード → 「次の機器を撮る」→ 件数 → 履歴・完了のボタン。

変更後（上から。処理の動きは変えない）:
1. `Text(if (saved == null) "点検中の撮影" else "撮影できました", headlineSmall)`（今のまま）
2. `Text(state.header, titleMedium)`
3. `Text(state.progress, titleLarge.gaugeNum(), color = Ink)`
4. 未撮影の機器（`saved == null && !saving` かつ `state.missingChips` が1台以上のとき）:
   - `Text("未撮影 ${state.missingChips.size}台", titleMedium)`
   - その下に `FlowRow(spacedBy 8.dp)` で `MissingChip` を並べる（このファイルの中の `private` 関数）:
     - `Surface(onClick = …, shape = MaterialTheme.shapes.small, color = GaugeColors.Dial, modifier = Modifier.heightIn(min = 48.dp).dashedOutline(GaugeColors.Ink, 2.dp, 4.dp))`
     - 中身は `Row(Modifier.padding(horizontal = 12.dp), verticalAlignment = CenterVertically, spacedBy(6.dp)) { StatusShape(MISSING, Ink, Modifier.size(18.dp)); Text("${device.name}（${device.id}）", labelLarge, color = Ink) }`
     - 押したときの処理は今のまま: `if (!shouldKeepQrTarget(target, device)) select(targetFromRoute(device))`
5. `DeviceQrSection`（今のまま）
6. 撮影する機器: `GaugeCard(kind = null)`。中身は上から:
   - `Text("撮影する機器", labelLarge, color = Steel)`
   - `Text(state.targetName, titleLarge)`
   - `Text(state.targetId, bodyLarge.gaugeNum(), color = Steel)`
   - `Text("出所：${state.targetSourceLabel}", bodyMedium, color = Steel)`（コロンを全角に）
   - `TextButton("機器名・IDを手入力する")`
7. カメラの許可・カメラの部分は今のまま（許可ボタンは `GaugePrimaryButton("許可")`）。
8. `if (saving) Text("保存中...", bodyLarge, color = Steel)`
9. 保存後: `GaugeCard(kind = GaugeKind.NEUTRAL)`。中身は上から:
   - `Thumbnail(…, fillMaxWidth().height(160.dp))`
   - `StatusBadge(NEUTRAL, "端末に保存済み")`
   - 機器名（`titleMedium`）
   - ID（`bodyMedium.gaugeNum()`、`Steel`）
   - 撮影時刻（`bodyMedium.gaugeNum()`、`Steel`）

   緑にしないのは、まだPCに届いていないため（1章「緑の札を出さない」）。
10. `GaugePrimaryButton("次の機器を撮る", …, fillMaxWidth, enabled = 今の条件)`
11. エラー文（今のまま）
12. `Text(state.countLine, titleMedium.gaugeNum())`
13. `GaugeSecondaryButton(履歴の文言は今のまま)`、`GaugeSecondaryButton("点検完了へ")`、`TextButton("点検一覧")`

「この点検を削除する」（`InspectionApp.kt:169`）は `GaugeDangerTextButton` にする。点検の削除ダイアログの「削除する」（`InspectionApp.kt:323-333`）も `GaugeDangerTextButton` にする。

### 6.7 履歴 `InspectionHistoryScreen`（PR4。機能追加 (a) を含む）

変更前: 見出し → 点検名 → 「写真N枚 ・ m / n機器」→ ルートの各機器のカード（「撮影済み：名前 ID（N枚）」＋「この機器を撮る」）→ 重複の注意（`tertiary` の文字）→ 写真の行（サムネイル・名前・ID・時刻・出所・撮り直す・削除）→ ボタン。送信状態の表示は無い。

変更後（`LazyColumn`、`padding(16.dp)`、`spacedBy(12.dp)`）:
1. 先頭の `item`:
   - `Text("この点検の履歴", headlineSmall)`
   - `Text(state.header, titleMedium)`
   - `Text("写真${state.photoCount}枚 ・ ${state.deviceLine}", titleLarge.gaugeNum(), color = Ink)`（例「写真3枚 ・ 撮影 1/2台」）
2. `state.noRouteNote`: `Text(it, bodyMedium, Steel)`
3. ルートがあるときだけ、`item { Text("ルートの機器", titleLarge) }` を置き、その下に各機器を `GaugeCard(kind = if (row.done) GaugeKind.OK else GaugeKind.MISSING)` で並べる。中身は:
   - `Row(verticalAlignment = CenterVertically)`:
     - 左 `Column(Modifier.weight(1f))`: `Text(row.device.name, titleMedium)`、`Text(row.device.id, bodyMedium.gaugeNum(), Steel)`
     - 右 `StatusBadge`: `row.done` なら `(OK, "撮影済み ${row.count}枚")`、そうでなければ `(MISSING, "未撮影")`
   - その下に `TextButton("この機器を撮る")`
4. 重複の注意（`state.notices`）: 1件ずつ `GaugeCard(kind = GaugeKind.WARN) { Text(it, bodyLarge) }`。`tertiary` の文字色はやめる。
5. `item { Text("撮影した写真", titleLarge) }`。写真が0枚なら `Text("写真はまだありません", bodyMedium, Steel)`
6. 写真の行: `GaugeCard(kind = row.sendKind, onClick = { onPhotoClick(row.item) })`。中身は `Row(spacedBy(12.dp))`:
   - 左: `Thumbnail(row.item.imagePath, Modifier.size(76.dp, 86.dp))`
   - 右 `Column(Modifier.weight(1f), spacedBy(4.dp))`:
     1. `StatusBadge(row.sendKind, row.sendLabel)` ← **(a) 送信状態**
     2. `Text(row.title, titleMedium)`
     3. `Text(row.idLine, bodyMedium.gaugeNum(), Steel)`
     4. `Text(row.timeLine, bodyMedium.gaugeNum(), Steel)`
     5. `Text("出所：${row.sourceLabel}", bodyMedium, Steel)`
     6. `row.reason?.let { Text("理由：$it", bodyMedium) }`
     7. `Row { TextButton("撮り直す", enabled = row.canEdit); GaugeDangerTextButton("削除", enabled = row.canEdit) }`
7. 最後の `item`（`Column(spacedBy(8.dp))`）: `GaugePrimaryButton("撮影へ戻る", fillMaxWidth)`、`GaugeSecondaryButton("点検完了へ", fillMaxWidth)`、`TextButton("点検一覧")`
8. 写真の削除ダイアログ（`DeleteInspectionPhotoDialog`）の「削除する」は `GaugeDangerTextButton`。

(a) のデータ:
- `HistoryRow`（`InspectionDisplay.kt:19`）の最後に、`val sendLabel: String = ""`、`val sendKind: GaugeKind = GaugeKind.WAIT`、`val reason: String? = null` を足す。
- `buildHistoryUiState`（`InspectionDisplay.kt:56`）の引数の最後に `currentReceiverId: String? = null` を足す。
  - その中で `val sendable: (QueueItem) -> Boolean = { isPhotoSendable(it, inspection.state) }` を作る。
  - 各行に次を入れる:
    - `sendLabel = sendStatusLabel(it, currentReceiverId, sendable)`
    - `sendKind = sendStatusKind(it, currentReceiverId, sendable)`
    - `reason = undeliveredReason(it)`
  - **生の `sendState` から札を作らない**（点検中は全行が `PENDING` なので、全部「未送信」と出てしまう）。
- 呼び出し側（`InspectionApp.kt:184`）で `currentReceiverId = settings.getReceiverId()` を渡す。
- 点検中に実際に出る札: 「完了後に送信」（`WAIT`、カード左端は細い灰の線）と「別のPC宛て（保留）」（`WARN`、左端は縞）。0章の1を参照。

### 6.8 完了確認 `InspectionCompleteScreen`（PR6）

- `Text("点検の完了確認", headlineSmall)`、`Text(state.title, titleMedium)`
- 件数: `Row(spacedBy(12.dp))` に `GaugeCard(kind = null, Modifier.weight(1f))` を2つ並べる。
  - 1つ目: `Text("写真", labelLarge, Steel)` と `Text("${state.photoCount}枚", headlineSmall.gaugeNum(), Ink)`
  - 2つ目: `Text("機器", labelLarge, Steel)` と `Text("${state.deviceCount}台", headlineSmall.gaugeNum(), Ink)`
- 注意: `state.warnings` が1件以上のとき、`GaugeCard(kind = if (state.warnings.any { it.startsWith("未撮影：") }) GaugeKind.MISSING else GaugeKind.WARN)`。中身は `Text("確認してください", titleMedium)` と、各行の `Text(it, bodyLarge)`。
- 案内の2文: `bodyMedium`、`Steel`。`blockReason`: エラー色のまま。
- `GaugePrimaryButton(state.completeLabel, onComplete, Modifier.fillMaxWidth().heightIn(min = 54.dp), enabled = state.canComplete)`
- `GaugeSecondaryButton("履歴に戻る", fillMaxWidth)`

### 6.9 送信状況 `InspectionSendStatusScreen`（PR6）

データ:
- `SendStatusUiState` の最後に `val badgeKind: GaugeKind = GaugeKind.WAIT` を足す。
- `SendRow` の最後に `val kind: GaugeKind = GaugeKind.WAIT` を足す（`reason` は PR3 で足し済み）。
- `buildSendStatusUiState` で:
  - `val summary = summarizeInspection(photos, inspection.routeSnapshot?.let { parseRouteJson(it)?.devices })`（ルート付きにする。`deviceCount` の値は変わらない）
  - `val badge = inspectionBadge(state, summary, undelivered)`
  - `badge = badge.label`、`badgeKind = badge.kind`
  - これで PR3 の #36 の文言も `inspectionBadge` から来るようにする（文字は同じ）
  - 行の `kind`: PC が未着と返した `SENT` の写真なら `WARN`。それ以外は `sendStatusKind(photo, currentReceiverId)`

画面（`LazyColumn`、`padding(16.dp)`、`spacedBy(12.dp)`）:
1. 先頭（`Column(spacedBy(8.dp))`）:
   - `StatusBadge(state.badgeKind, state.badge)`
   - `Text(state.headline, headlineSmall)`
   - `Text(state.summaryLine, bodyMedium.gaugeNum(), Steel)`
   - `Text(state.photoProgress, titleLarge.gaugeNum(), Ink)`（例「到着 3/5枚」）
   - `Text(state.manifestLine, bodyMedium)`
   - `state.guidance?.let { GaugeCard(kind = null) { Text(it, bodyLarge) } }`
2. 行: `GaugeCard(kind = row.kind)`。中身は `Row(spacedBy(12.dp))`:
   - 左: `Thumbnail(76.dp)`
   - 右 `Column(weight 1f, spacedBy(4.dp))`:
     - `StatusBadge(row.kind, row.status)`
     - `Text(row.title, titleMedium)`
     - `Text(row.idLine, bodyMedium.gaugeNum(), Steel)`
     - `Text(row.timeLine, bodyMedium.gaugeNum(), Steel)`
     - `row.reason?.let { Text("理由：$it", bodyMedium) }`
     - `if (row.heldForOtherPc) TextButton("今のPCへ送り直す")`
3. 最後（`Column(spacedBy(8.dp))`）:
   - `GaugePrimaryButton`: 「今すぐ送る」「未着の写真を再送」「写真の一覧だけ再送」。それぞれ今の表示条件のまま、`fillMaxWidth`。
   - `TextButton("接続の案内を見る")`（今の条件）
   - `TextButton("点検の一覧へ")`

### 6.10 接続の案内 `ConnectionGuideScreen`（PR6）

- `Text("PCにつながりません", headlineSmall)`
- `GaugeCard(kind = null)` の中に、案内の文と手順1〜3、注記を `bodyLarge` で並べる。手順3は5.1節 #46。注記「設定項目の場所は…」は `bodyMedium`、`Steel`。
- 今の接続: `Text("今の接続：$networkLabel", bodyLarge)` の下に `StatusBadge`。`reachable` の値で次のどれかにする。
  - `true` → `(OK, "PCに接続中")`
  - `false` → `(WARN, "PCにつながりません")`
  - `null` → `(WAIT, "確認中")`
- `GaugePrimaryButton("送信先の設定", fillMaxWidth)`、`TextButton("点検の一覧へ")`

### 6.11 ダイアログと従来の画面

- ダイアログ（`ReceiverSettingsDialog`、`InspectionApp.kt` の `AlertDialog` 各種、`ManualDeviceDialog`、`FullImageDialog`、`PairingScreen`）は、テーマだけで色・文字が変わる。コードは、削除ボタン（6.6・6.7節）以外は変えない。
- 従来の画面（`MeterCaptureApp`、`QueueListScreen`、`DeviceQrSection`、`CaptureMetaForm`、`CameraCapturePanel`、`QrScanPanel`）も同じ。PR1 のテーマと PR3 の文言だけを当て、並びは変えない。

---

## 7. 実装の分割（PR ごと。1つ約3時間。この順に1つずつ）

共通の決まり（全PR）:
- **ponytail（最小の実装）で。** 頼まれていない機能・テスト・抽象化を足さない。
- **触らないもの:**
  - `ui/` 以外の Kotlin（`queue/`・`inspection/`・`settings/`・`pairing/`・`route/`・`device/`・`capture/`・`MainActivity.kt`）
  - 送信・保存・QR・ネットワークの処理
  - `build.gradle.kts`・`libs.versions.toml`（依存を足さない。PR7 も依存は足さない）
- **止まる条件:** 本体（`ui/` 以外）のバグを見つけた、表に無いテストが落ちた、この設計書と実物の行番号・中身が食い違う。このどれかのときは、直さずに止まって日報で報告する。
- 始める前: `git switch main` → `git pull` → `git switch -c <ブランチ名>`。前のPRがマージされてから次を始める（`InspectionDisplay.kt`・`InspectionApp.kt` を何度も触るため）。
- 確認コマンド（PowerShell、リポジトリの直下から）:
  - `cd android; .\gradlew.bat testDebugUnitTest` → 最後に `BUILD SUCCESSFUL`
  - `.\gradlew.bat assembleDebug` → `BUILD SUCCESSFUL`
  - 着手前にも一度 `testDebugUnitTest` を流し、テストの件数を日報に書く（終わったあとも書く。件数が減っていないこと）
- 実機確認: `.\gradlew.bat installDebug` で SO-52E に入れる。そのPRの「確認する画面」をスクリーンショットに撮り、日報に付ける。
- PR は `main` 向け。説明に「設計書 `tasks/design/Android-計器盤デザイン.md` の PRn」と書く。マージはユーザーが判断する。

| PR | ブランチ | 中身 | 触るファイル | 受入条件 | 確認する画面 |
|---|---|---|---|---|---|
| 1 | `feat/android-gauge-1` | テーマとトークンの導入だけ | 新規 `ui/theme/GaugeTheme.kt`（4.1節のとおり）／新規 `res/values/colors.xml`（`<color name="gauge_panel">#FFE3E6E4</color>` の1つだけ）／`res/values/themes.xml`（`<item name="android:windowBackground">@color/gauge_panel</item>` を1行足す）／`ui/inspection/InspectionApp.kt:115` の `MaterialTheme {` を `GaugeTheme {` に／`ui/MeterCaptureApp.kt:104` も同じ（両方変えないと従来画面が紫に戻る） | テスト・ビルドが通る。既存ファイルの日本語の文字列リテラルに変更が無い（新規ファイルのコメントは数えない）。画面の地が `#E3E6E4`、主ボタンが紺、ダイアログの地が `#F8F8F5`。紫が1か所も残らない | 点検の一覧、新しい点検、送信先の設定ダイアログ、従来の画面 |
| 2 | `feat/android-gauge-2` | 共通部品とヘッダー・接続帯 | 新規 `ui/components/GaugeKind.kt`・`GaugeDraw.kt`・`StatusBadge.kt`・`GaugeCard.kt`・`GaugeButtons.kt`・`TickRule.kt`（4.2節）／`ui/ConnectionBar.kt`（6.2節）／`ui/inspection/InspectionScaffold.kt`（6.1節） | テスト・ビルドが通る。既存ファイルの日本語の文字列リテラルに変更が無い。接続帯の4状態の色が6.2節のとおり（送信先の設定を空にする・PCの受信口を止める・付ける、で確かめる）。見出しの下に目盛りの定規 | 点検の一覧（帯「接続中」「届かない」「未設定」の3枚） |
| 3 | `feat/android-gauge-3` | **(b) 言葉をそろえる**（未着理由・台・ルート）と、送信状況の行の理由 | 5.1節の表のファイル（`ConnectionStatus.kt`・`QueueDisplay.kt`・`QueueListScreen.kt`・`MeterCaptureApp.kt`・`PairingScreen.kt`・`InspectionDisplay.kt`・`InspectionSendStatusScreen.kt`・`ConnectionGuideScreen.kt`・`InspectionCreateScreen.kt`・`RouteListScreen.kt`・`InspectionApp.kt`）／4.3節の `reasonFromLastError`・`undeliveredReason`、`errorTextFor` の書き換え／5.3節の `SendRow.reason`／5.4節のテストの期待値／テストを1つ足す: `QueueDisplayTest` に `reasonFromLastErrorMapsRawErrors`（R1〜R7 を各1行の `assertEquals`。例 `assertEquals("合言葉が違います", reasonFromLastError("PC未接続: Health check failed with HTTP 401: x"))`。それに加えて `assertEquals("接続できません", reasonFromLastError("PC未接続: 接続できません"))` の1行） | テスト・ビルドが通る。直した期待値は5.4節の行だけ。5.1節の旧文言が `ui/` に残っていない。確かめ方: リポジトリ直下で `git grep -n -e 未到着 -e 届いていません -e 届かない -e PC受信済み -e "機器）" -e 対象一覧 -e 一覧外 -- android/app/src/main/kotlin/jp/sotuken/metercapture/ui` を実行し、出てよいのは M1（5.2節）の比較に使う `"PCに届かないため、写真の一覧を送れませんでした"` の1行だけ。コメントに残る旧い言葉、例えば `QueueDisplay.kt:7`・`:35`・`:53` も、2章の表に従って書き換える | 送信状況（未着がある点検。PCを止めて完了→送信待ちで「理由：接続できません」が出る） |
| 4 | `feat/android-gauge-4` | 撮影と履歴の見た目と、**(a) 履歴の送信状態** | `ui/inspection/InspectionCaptureScreen.kt`（6.6節）／`ui/inspection/InspectionHistoryScreen.kt`（6.7節）／`ui/inspection/InspectionDisplay.kt`（`HistoryRow` の3つの引数、`buildHistoryUiState` の `currentReceiverId`）／`ui/QueueDisplay.kt`（`sendStatusKind`）／`ui/inspection/InspectionApp.kt`（`:184` に受信口IDを渡す、削除ボタン2か所）／テストを2つ足す: `QueueDisplayTest` に `sendStatusKindFollowsLabelOrder`（3.6節の表の写真の行9つを各1行で）、`HistoryUiStateTest` に `historyRowShowsSendStateWhileInProgress`（点検中の写真 → `"完了後に送信"`・`WAIT`、`receiverId = "old"` で `currentReceiverId = "new"` の写真 → `"別のPC宛て（保留）"`・`WARN`） | テスト・ビルドが通る。履歴の全行に送信状態の札が出る。未撮影の機器が破線で囲まれる。点検中の M3 の `Card`・`OutlinedButton` が撮影・履歴の画面に残っていない | 撮影（未撮影あり・保存直後）、履歴（ルートあり、写真2枚以上） |
| 5 | `feat/android-gauge-5` | 点検の一覧・新しい点検・ルート | `ui/inspection/InspectionHomeScreen.kt`（6.3節）／`ui/inspection/InspectionDisplay.kt`（`HomeCard` の4つの引数、`inspectionBadge`・`extraBadges`・`formatStartedLabel`、`buildHomeUiState`）／`ui/inspection/InspectionCreateScreen.kt`（6.4節）／`ui/inspection/RouteListScreen.kt`（6.5節）／テストを1つ足す: `HomeUiStateTest` に `sentBadgeTurnsNeutralWhenRouteDeviceMissing`（SENT・未撮影0 → `OK` `"送信済み"`、SENT・未撮影1 → `NEUTRAL` `"送信済み（要確認あり）"` と追加の札 `MISSING` `"未撮影 1台"`、`edgeKind == MISSING`） | テスト・ビルドが通る。未撮影・未着がある点検に緑の札が出ない。カード左端が3.6節のとおり | 点検の一覧（作業中・送信待ち・送信済み・未着ありが並んだ状態）、新しい点検、ルート |
| 6 | `feat/android-gauge-6` | 完了確認・送信状況・接続の案内 | `ui/inspection/InspectionCompleteScreen.kt`（6.8節）／`ui/inspection/InspectionSendStatusScreen.kt`（6.9節）／`ui/inspection/ConnectionGuideScreen.kt`（6.10節）／テストを1つ足す: `SendStatusUiStateTest` に `incompleteBadgeAndMissingRowAreWarn`（SENT_INCOMPLETE → `badgeKind == WARN`、PC未着の行 → `kind == WARN`・`reason == "PCで写真が見つかりません"`） | テスト・ビルドが通る。この3画面に M3 の `Card`・`OutlinedCard`・素の `Button` が残っていない | 完了確認（注意あり）、送信状況（送信済み・未着あり）、接続の案内 |
| 7（当面しない） | `feat/android-gauge-7` | 書体の同梱は当面しない | なし | 実施しない | なし |


### PR8 `feat/android-gauge-8`: SK-08 撮影したときの反応

- 前提: PR4のあと。正本は `tasks/design/Android-接続状況バーとSK-08-DESIGN.md` のSK-08節。
- 触るファイル: `ui/inspection/InspectionCaptureScreen.kt` と必要な `ui/` 内のファイルだけ。
- シャッターを押した瞬間、画面全体に白い光を約150ms表示してフェードアウトする。白は3章の `OnInk` を使う。これ以外の動きは足さない。
- 保存完了後、画面下に `保存しました（今日 N枚目）` を2秒表示する。Nは端末の日付で今日撮ったキュー項目数。表示には3章の `Ink`・`OnInk` を使う。保存失敗時は既存のエラー表示を維持する。
- 撮影を連打しても反応は溜めず、直近の1回だけ表示する。その他の時間の数値は正本に記載なし。
- 受入条件: 撮影時に約150msの白い光がフェードアウトし、保存成功後に正しい枚数の文言が2秒出る。失敗時は既存エラーを表示し、連打時は反応が溜まらない。変更は `ui/` 内だけで、テストとビルドが通る。
- 確認する画面: 撮影画面（保存成功・失敗・連打）。確認コマンド: `cd android; .\gradlew.bat testDebugUnitTest`、`.\gradlew.bat assembleDebug`。

---

## 8. しないこと（非目標）

- 文字盤の絵、針、許容範囲の帯（スマホには読み取り値が無い）。
- SK-08の白い光以外のアニメーション（1章）。ダークモード、壁紙の色。
- 送信状態・点検状態を新しく増やすこと（3.6節は、今の `SendState`・`InspectionState` だけを使う）。
- 点検中に写真を送るように変えること（0章の1）。
- `queue/`・`inspection/` 等で作る生のエラー文を書き換えること（5.2節は表示のときに置き換えるだけ）。
- Compose の画面テスト（UIテスト）を足すこと。見た目は実機のスクリーンショットで確かめる。
- `CompositionLocal` による色の受け渡し（0章の6）。
