package jp.sotuken.metercapture.queue.sender

import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Base64
import jp.sotuken.metercapture.queue.QueueItem

object SenderPayloads {
    private val timestampFormatter: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss")
        .withZone(ZoneOffset.UTC)

    fun buildBaseName(item: QueueItem): String {
        val timestamp = timestampFormatter.format(Instant.parse(item.capturedAt))
        return "${timestamp}_${item.localId}"
    }

    fun buildImageFileName(item: QueueItem): String {
        val baseName = buildBaseName(item)
        val sourceImage = File(item.imagePath)
        val imageExtension = sourceImage.extension.ifBlank { "jpg" }
        return "$baseName.$imageExtension"
    }

    fun buildSidecarJson(item: QueueItem): String = buildString {
        append('{')
        append("\"local_id\":").append(jsonString(item.localId)).append(',')
        append("\"captured_at\":").append(jsonString(item.capturedAt)).append(',')
        append("\"device_name\":").append(jsonStringOrNull(item.deviceName)).append(',')
        append("\"operator_value\":").append(jsonNumberOrNull(item.operatorValue)).append(',')
        append("\"operator_note\":").append(jsonStringOrNull(item.operatorNote))
        append('}')
    }

    fun buildSidecarJsonBase64Url(item: QueueItem): String {
        val jsonBytes = buildSidecarJson(item).toByteArray(Charsets.UTF_8)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(jsonBytes)
    }

    fun computeSha256Hex(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        return digest.joinToString("") { "%02x".format(it) }
    }

    fun computeSha256Hex(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(8192)
            var bytesRead: Int
            while (input.read(buffer).also { bytesRead = it } != -1) {
                digest.update(buffer, 0, bytesRead)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun jsonString(value: String): String = "\"${escape(value)}\""

    private fun jsonStringOrNull(value: String?): String = if (value == null) "null" else jsonString(value)

    private fun jsonNumberOrNull(value: Double?): String = value?.toString() ?: "null"

    private fun escape(value: String): String = buildString {
        for (char in value) {
            when (char) {
                '\\' -> append("\\\\")
                '"' -> append("\\\"")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> if (char < ' ') append("\\u%04x".format(char.code)) else append(char)
            }
        }
    }
}
