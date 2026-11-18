package jp.sotuken.metercapture.ui.components

/** 状態の種類。設計書3.6節。 */
enum class GaugeKind { OK, WARN, FAIL, MISSING, WAIT, NEUTRAL }

/** 札1枚ぶんの中身。 */
data class BadgeSpec(val kind: GaugeKind, val label: String)

/** カード左端に使う種類。MISSING → FAIL → WARN → WAIT → NEUTRAL → OK の順で最初に見つかったもの。空なら NEUTRAL。 */
fun edgeKindOf(kinds: Collection<GaugeKind>): GaugeKind =
    listOf(GaugeKind.MISSING, GaugeKind.FAIL, GaugeKind.WARN, GaugeKind.WAIT, GaugeKind.NEUTRAL, GaugeKind.OK)
        .firstOrNull { it in kinds } ?: GaugeKind.NEUTRAL
