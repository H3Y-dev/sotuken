package jp.sotuken.metercapture.ui

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureStorageTest {

    @Test
    fun generateFileName_formatsCorrectly() {
        val instant = Instant.parse("2026-09-08T01:30:00Z")
        val fileName = CaptureStorage.generateFileName(instant)
        assertTrue("File name should start with meter_", fileName.startsWith("meter_"))
        assertTrue("File name should end with .jpg", fileName.endsWith(".jpg"))
    }

    @Test
    fun capturedAt_iso8601Format_canBeParsed() {
        val now = Instant.now()
        val capturedAt = now.toString()
        val parsed = Instant.parse(capturedAt)
        assertNotNull(parsed)
        assertEquals(now.epochSecond, parsed.epochSecond)
    }
}