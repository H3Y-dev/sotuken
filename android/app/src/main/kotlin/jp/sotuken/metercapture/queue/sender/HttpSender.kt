package jp.sotuken.metercapture.queue.sender

import java.io.File
import java.io.FileNotFoundException
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import jp.sotuken.metercapture.queue.QueueItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Wi-Fi経由で手元PCの受信口（manager/receiver.py）へ画像を送信するSender。
 * 外部依存なし（HttpURLConnection のみ）。
 */
class HttpSender(
    private val baseUrl: String,
    private val token: String,
    private val connectTimeoutMs: Int = DEFAULT_SEND_CONNECT_TIMEOUT_MS,
    private val readTimeoutMs: Int = DEFAULT_SEND_READ_TIMEOUT_MS,
) : Sender {

    override suspend fun send(item: QueueItem): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val imageFile = File(item.imagePath)
            if (!imageFile.exists()) {
                throw FileNotFoundException("Image file does not exist: ${item.imagePath}")
            }

            val imageBytes = imageFile.readBytes()
            val fileName = SenderPayloads.buildImageFileName(item)
            val sidecarB64 = SenderPayloads.buildSidecarJsonBase64Url(item)
            val sha256Hex = SenderPayloads.computeSha256Hex(imageBytes)

            val uploadUrl = buildUrl(baseUrl, "/upload")
            val connection = (uploadUrl.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = connectTimeoutMs
                readTimeout = readTimeoutMs
                doOutput = true
                instanceFollowRedirects = false
                setRequestProperty("X-Sotuken-Token", token)
                setRequestProperty("X-File-Name", fileName)
                setRequestProperty("X-Sidecar-Json", sidecarB64)
                setRequestProperty("X-Image-Sha256", sha256Hex)
                setRequestProperty("Content-Type", "application/octet-stream")
                setFixedLengthStreamingMode(imageBytes.size)
            }

            try {
                connection.outputStream.use { output ->
                    output.write(imageBytes)
                    output.flush()
                }

                val responseCode = connection.responseCode
                if (responseCode == HttpURLConnection.HTTP_OK) {
                    Unit
                } else {
                    val errorBody = readResponseText(connection)
                    throw IOException("Upload failed with HTTP $responseCode: $errorBody")
                }
            } finally {
                connection.disconnect()
            }
        }
    }

    fun health(): Result<Unit> = health(baseUrl, token)

    companion object {
        const val HEALTH_CONNECT_TIMEOUT_MS = 2000
        const val HEALTH_READ_TIMEOUT_MS = 3000
        const val DEFAULT_SEND_CONNECT_TIMEOUT_MS = 10000
        const val DEFAULT_SEND_READ_TIMEOUT_MS = 30000

        /**
         * 受信口の疎通確認（GET /health）。
         * 接続2秒・読み取り3秒でタイムアウト。
         */
        fun health(
            baseUrl: String,
            token: String,
            connectTimeoutMs: Int = HEALTH_CONNECT_TIMEOUT_MS,
            readTimeoutMs: Int = HEALTH_READ_TIMEOUT_MS,
        ): Result<Unit> = runCatching {
            val healthUrl = buildUrl(baseUrl, "/health")
            val connection = (healthUrl.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = connectTimeoutMs
                readTimeout = readTimeoutMs
                instanceFollowRedirects = false
                setRequestProperty("X-Sotuken-Token", token)
            }

            try {
                val responseCode = connection.responseCode
                if (responseCode == HttpURLConnection.HTTP_OK) {
                    Unit
                } else {
                    val errorBody = readResponseText(connection)
                    throw IOException("Health check failed with HTTP $responseCode: $errorBody")
                }
            } finally {
                connection.disconnect()
            }
        }

        private fun buildUrl(baseUrl: String, endpoint: String): URL {
            val cleanBase = baseUrl.trimEnd('/')
            val cleanEndpoint = if (endpoint.startsWith("/")) endpoint else "/$endpoint"
            return URL("$cleanBase$cleanEndpoint")
        }

        private fun readResponseText(connection: HttpURLConnection): String {
            val stream = connection.errorStream ?: runCatching { connection.inputStream }.getOrNull()
            return stream?.bufferedReader()?.use { it.readText() } ?: ""
        }
    }
}
