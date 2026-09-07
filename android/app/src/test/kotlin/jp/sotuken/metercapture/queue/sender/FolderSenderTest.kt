package jp.sotuken.metercapture.queue.sender

import java.io.File
import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.SendState
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FolderSenderTest {
    @Test
    fun sendWritesImageAndSidecarJsonWithExpectedNames() = runTest {
        withTemporaryDirs { imageFile, outputDir ->
            val sender = FolderSender(outputDir)
            val item = fullItem(imageFile)

            val result = sender.send(item)

            assertTrue(result.isSuccess)
            val expectedBase = "20260907T053000_${item.localId}"
            assertTrue(File(outputDir, "$expectedBase.jpg").exists())
            assertTrue(File(outputDir, "$expectedBase.json").exists())
        }
    }

    @Test
    fun sendDoesNotLeaveTemporaryPartFilesBehind() = runTest {
        withTemporaryDirs { imageFile, outputDir ->
            val sender = FolderSender(outputDir)
            sender.send(fullItem(imageFile))

            val partFiles = outputDir.listFiles { file -> file.name.endsWith(".part") }
            assertTrue(partFiles?.isEmpty() ?: true)
        }
    }

    @Test
    fun sidecarJsonContainsAllFiveFieldsWithValues() = runTest {
        withTemporaryDirs { imageFile, outputDir ->
            val sender = FolderSender(outputDir)
            val item = fullItem(imageFile)
            sender.send(item)

            val jsonFile = File(outputDir, "20260907T053000_${item.localId}.json")
            val json = jsonFile.readText()

            assertTrue(json.contains("\"local_id\":\"${item.localId}\""))
            assertTrue(json.contains("\"captured_at\":\"2026-09-07T05:30:00Z\""))
            assertTrue(json.contains("\"device_name\":\"圧力計A\""))
            assertTrue(json.contains("\"operator_value\":0.5"))
            assertTrue(json.contains("\"operator_note\":\"昇圧前\""))
        }
    }

    @Test
    fun sidecarJsonWritesNullForMissingOptionalFieldsRatherThanOmittingKeys() = runTest {
        withTemporaryDirs { imageFile, outputDir ->
            val sender = FolderSender(outputDir)
            val item = QueueItem(
                localId = "local-1",
                imagePath = imageFile.absolutePath,
                capturedAt = "2026-09-07T05:30:00Z",
                deviceName = null,
                operatorValue = null,
                operatorNote = null,
                sendState = SendState.SENDING,
                retryCount = 0,
                lastError = null,
                sentAt = null,
            )
            sender.send(item)

            val jsonFile = File(outputDir, "20260907T053000_local-1.json")
            val json = jsonFile.readText()

            assertTrue(json.contains("\"device_name\":null"))
            assertTrue(json.contains("\"operator_value\":null"))
            assertTrue(json.contains("\"operator_note\":null"))
        }
    }

    @Test
    fun sendReturnsFailureWhenSourceImageIsMissing() = runTest {
        withTemporaryDirs { imageFile, outputDir ->
            val sender = FolderSender(outputDir)
            val missingImage = File(imageFile.parentFile, "does-not-exist.jpg")
            val item = fullItem(missingImage)

            val result = sender.send(item)

            assertFalse(result.isSuccess)
        }
    }

    private fun fullItem(imageFile: File) = QueueItem(
        localId = "3f9c1e2a-0000-0000-0000-000000000001",
        imagePath = imageFile.absolutePath,
        capturedAt = "2026-09-07T05:30:00Z",
        deviceName = "圧力計A",
        operatorValue = 0.5,
        operatorNote = "昇圧前",
        sendState = SendState.SENDING,
        retryCount = 0,
        lastError = null,
        sentAt = null,
    )

    private suspend fun withTemporaryDirs(block: suspend (imageFile: File, outputDir: File) -> Unit) {
        val workDir = File.createTempFile("folder-sender-test-", "").apply {
            delete()
            mkdirs()
        }
        val imageFile = File(workDir, "source.jpg").apply { writeText("fake-image-bytes") }
        val outputDir = File(workDir, "meter_inbox_incoming")

        try {
            block(imageFile, outputDir)
        } finally {
            workDir.deleteRecursively()
        }
    }
}
