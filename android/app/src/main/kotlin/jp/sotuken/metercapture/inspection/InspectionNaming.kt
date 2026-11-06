package jp.sotuken.metercapture.inspection

import java.time.Instant
import java.time.ZonedDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.UUID

val INSPECTION_ID_PATTERN = Regex("[A-Za-z0-9._-]{1,64}")

fun newInspectionId(now: Instant, random: () -> String = { UUID.randomUUID().toString().take(8) }): String =
    "INS-${DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'").withZone(ZoneOffset.UTC).format(now)}-${random()}"

fun timeSlotLabel(hour: Int): String = when (hour) {
    in 4..10 -> "朝"
    in 11..14 -> "昼"
    in 15..18 -> "夕方"
    else -> "夜"
}

fun defaultInspectionName(now: ZonedDateTime, existingNames: Collection<String>): String {
    val base = "${now.format(DateTimeFormatter.ofPattern("MM/dd"))} ${timeSlotLabel(now.hour)}の点検"
    if (base !in existingNames) return base
    var sequence = 2
    while ("$base $sequence" in existingNames) sequence++
    return "$base $sequence"
}

fun normalizeInspectionText(raw: String): String? {
    require(raw.codePoints().noneMatch { Character.getType(it).toByte() in setOf(Character.CONTROL, Character.FORMAT, Character.SURROGATE, Character.PRIVATE_USE, Character.UNASSIGNED) })
    val text = raw.trim()
    if (text.isEmpty()) return null
    require(text.codePointCount(0, text.length) <= 64)
    return text
}
