package jp.sotuken.metercapture.capture

import java.nio.file.Files
import java.util.TimeZone
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureFileNamingTest {
    @Test
    fun captureFileNameFormatsKnownEpochMillis() {
        val fileName = captureFileName(123L, TimeZone.getTimeZone("UTC"))

        assertEquals("19700101_000000_123.jpg", fileName)
    }

    @Test
    fun capturesDirCreatesMissingDirectory() {
        val baseDir = Files.createTempDirectory("capture-dir-test-").toFile()
        try {
            val expected = baseDir.resolve("captures")
            assertFalse(expected.exists())

            val actual = capturesDir(baseDir)

            assertEquals(expected, actual)
            assertTrue(actual.isDirectory)
        } finally {
            baseDir.deleteRecursively()
        }
    }
}
