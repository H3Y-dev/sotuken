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
