package jp.sotuken.metercapture.inspection

import java.time.*
import org.junit.Assert.*
import org.junit.Test

class InspectionNamingTest {
    @Test fun inspectionIdMatchesPatternAndIsUtc() {
        val id = newInspectionId(Instant.parse("2026-11-06T00:30:12Z")) { "1a2b3c4d" }
        assertEquals("INS-20261106T003012Z-1a2b3c4d", id)
        assertTrue(INSPECTION_ID_PATTERN.matches(id))
        assertEquals(29, id.length)
    }
    @Test fun timeSlotBoundaries() {
        mapOf(3 to "夜", 4 to "朝", 10 to "朝", 11 to "昼", 14 to "昼", 15 to "夕方", 18 to "夕方", 19 to "夜", 23 to "夜", 0 to "夜").forEach { (hour, label) -> assertEquals(label, timeSlotLabel(hour)) }
    }
    @Test fun defaultNameUsesLocalDate() = assertEquals("11/06 朝の点検", defaultInspectionName(Instant.parse("2026-11-05T20:00:00Z").atZone(ZoneId.of("Asia/Tokyo")), emptyList()))
    @Test fun defaultNameAddsSequenceWhenTaken() = assertEquals("11/06 朝の点検 3", defaultInspectionName(ZonedDateTime.parse("2026-11-06T09:00:00+09:00"), listOf("11/06 朝の点検", "11/06 朝の点検 2")))
    @Test fun normalizeTextTrimsAndRejectsLongOrControl() {
        assertEquals("点検", normalizeInspectionText("  点検  "))
        assertNull(normalizeInspectionText("  "))
        assertEquals("あ".repeat(64), normalizeInspectionText("あ".repeat(64)))
        listOf("あ".repeat(65), "a\nb", "a\u0000b", "a\u200bb").forEach { assertTrue(runCatching { normalizeInspectionText(it) }.isFailure) }
    }
}
