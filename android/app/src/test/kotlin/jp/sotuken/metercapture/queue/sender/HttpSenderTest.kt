package jp.sotuken.metercapture.queue.sender

import java.io.BufferedInputStream
import java.io.EOFException
import java.io.File
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.SocketException
import java.net.SocketTimeoutException
import java.util.Base64
import kotlin.concurrent.thread
import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.SendState
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class HttpSenderTest {

    private lateinit var server: ServerSocket
    private lateinit var serverThread: Thread
    @Volatile private var serverFailure: Throwable? = null
    private var serverPort: Int = 0
    @Volatile private var lastRequestLine: String? = null
    @Volatile private var lastReceivedFileName: String? = null
    @Volatile private var lastReceivedSidecarJson: String? = null
    @Volatile private var lastReceivedSha256: String? = null
    @Volatile private var lastReceivedBody: ByteArray? = null

    private val validToken = "test-secret-token"
    @Volatile private var uploadStatus: String = "200 OK"
    @Volatile private var manifestResponse: String = """{"ok":true,"matched":1,"missing_photos":[]}"""
    @Volatile private var manifestBody: String? = null
    @Volatile private var manifestToken: String? = null
    @Volatile private var manifestContentType: String? = null
    @Volatile private var loseUploadResponse = false

    @Before
    fun setUp() {
        server = ServerSocket().apply { bind(InetSocketAddress("127.0.0.1", 0)) }
        serverPort = server.localPort
        serverThread = thread(name = "http-sender-test", isDaemon = true) {
            try {
                while (!server.isClosed) {
                    server.accept().use { socket ->
                        socket.soTimeout = 5000
                        val input = BufferedInputStream(socket.getInputStream())
                        val requestLine = readLine(input)
                        lastRequestLine = requestLine
                        val headers = mutableMapOf<String, String>()
                        while (true) {
                            val line = readLine(input)
                            if (line.isEmpty()) break
                            headers[line.substringBefore(':').lowercase()] = line.substringAfter(':').trim()
                        }
                        val body = ByteArray(headers["content-length"]?.toInt() ?: 0)
                        var offset = 0
                        while (offset < body.size) {
                            val count = input.read(body, offset, body.size - offset)
                            if (count < 0) throw EOFException("Incomplete HTTP body")
                            offset += count
                        }
                        if (requestLine.startsWith("POST /upload ")) {
                            lastReceivedFileName = headers["x-file-name"]
                            lastReceivedSidecarJson = headers["x-sidecar-json"]
                            lastReceivedSha256 = headers["x-image-sha256"]
                            lastReceivedBody = body
                        }
                        val status = if (headers["x-sotuken-token"] == validToken) uploadStatus else "401 Unauthorized"
                        val isManifest = requestLine.contains("/manifest ")
                        if (isManifest) {
                            manifestBody = body.toString(Charsets.UTF_8)
                            manifestToken = headers["x-sotuken-token"]
                            manifestContentType = headers["content-type"]
                        }
                        val response = (if (isManifest) manifestResponse else """{"ok":true}""").toByteArray(Charsets.UTF_8)
                        if (loseUploadResponse && requestLine.startsWith("POST /upload ")) {
                            Thread.sleep(300)
                        } else socket.getOutputStream().apply {
                            write(("HTTP/1.1 $status\r\nContent-Type: application/json\r\n" +
                                "Content-Length: ${response.size}\r\nConnection: close\r\n\r\n").toByteArray(Charsets.US_ASCII))
                            write(response)
                            flush()
                        }
                    }
                }
            } catch (e: SocketException) {
                if (!server.isClosed) serverFailure = e
            } catch (e: Throwable) {
                serverFailure = e
            }
        }
    }

    @After
    fun tearDown() {
        server.close()
        serverThread.join(6000)
        assertFalse("HTTP server thread did not stop", serverThread.isAlive)
        serverFailure?.let { throw AssertionError("HTTP server failed", it) }
    }

    // Read headers and body from the same byte stream so a Reader cannot consume body bytes.
    private fun readLine(input: BufferedInputStream): String {
        val line = StringBuilder()
        while (true) {
            val next = input.read()
            if (next < 0) throw EOFException("Incomplete HTTP headers")
            if (next == '\n'.code) return line.toString().removeSuffix("\r")
            line.append(next.toChar())
        }
    }

    @Test
    fun healthCheckReturnsSuccessWhenTokenMatches() = runTest {
        val result = HttpSender.health("http://127.0.0.1:$serverPort", validToken)
        assertTrue(result.isSuccess)
        assertEquals("GET /health HTTP/1.1", lastRequestLine)
    }

    @Test
    fun healthCheckReturnsFailureWhenTokenMismatches() = runTest {
        val result = HttpSender.health("http://127.0.0.1:$serverPort", "wrong-token")
        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()?.message?.contains("401") == true)
    }

    @Test
    fun healthCheckReturnsFailureWhenConnectionRefused() = runTest {
        val unusedPort = findUnusedPort()
        val result = HttpSender.health("http://127.0.0.1:$unusedPort", validToken)
        assertTrue(result.isFailure)
    }

    @Test
    fun sendSucceedsAndServerReceivesExpectedHeadersAndBody() = runTest {
        val imageFile = File.createTempFile("http-sender-test-", ".jpg").apply {
            writeBytes("mock-image-content-for-upload".toByteArray())
        }

        try {
            val item = QueueItem(
                localId = "local-1234",
                imagePath = imageFile.absolutePath,
                capturedAt = "2026-10-21T10:00:00Z",
                deviceName = "TestDevice",
                operatorValue = 42.0,
                operatorNote = "Note\u0000\b\u000c",
                sendState = SendState.SENDING,
                retryCount = 0,
                lastError = null,
                sentAt = null,
            )

            val sender = HttpSender("http://127.0.0.1:$serverPort", validToken)
            val result = sender.send(item)

            assertTrue(result.isSuccess)
            assertEquals("POST /upload HTTP/1.1", lastRequestLine)
            assertEquals("20261021T100000_local-1234.jpg", lastReceivedFileName)
            assertEquals(
                SenderPayloads.buildSidecarJsonBase64Url(item),
                lastReceivedSidecarJson,
            )
            val sidecar = String(Base64.getUrlDecoder().decode(lastReceivedSidecarJson), Charsets.UTF_8)
            assertTrue(sidecar.contains("\"operator_note\":\"Note\\u0000\\u0008\\u000c\""))
            assertFalse(sidecar.any { it < ' ' })
            val expectedSha = SenderPayloads.computeSha256Hex(imageFile.readBytes())
            assertEquals(expectedSha, lastReceivedSha256)
            assertEquals("mock-image-content-for-upload", lastReceivedBody?.toString(Charsets.UTF_8))
        } finally {
            imageFile.delete()
        }
    }

    @Test
    fun sendReturnsFailureWhenTokenIsInvalid() = runTest {
        val imageFile = File.createTempFile("http-sender-test-", ".jpg").apply {
            writeBytes("image-data".toByteArray())
        }

        try {
            val item = QueueItem(
                localId = "local-401",
                imagePath = imageFile.absolutePath,
                capturedAt = "2026-10-21T10:00:00Z",
                deviceName = null,
                operatorValue = null,
                operatorNote = null,
                sendState = SendState.SENDING,
                retryCount = 0,
                lastError = null,
                sentAt = null,
            )

            val sender = HttpSender("http://127.0.0.1:$serverPort", "wrong-token")
            val result = sender.send(item)

            assertTrue(result.isFailure)
            assertTrue(result.exceptionOrNull()?.message?.contains("401") == true)
        } finally {
            imageFile.delete()
        }
    }

    @Test
    fun sendReturnsFailureWhenConnectionRefused() = runTest {
        val imageFile = File.createTempFile("http-sender-test-", ".jpg").apply {
            writeBytes("image-data".toByteArray())
        }

        try {
            val item = QueueItem(
                localId = "local-refused",
                imagePath = imageFile.absolutePath,
                capturedAt = "2026-10-21T10:00:00Z",
                deviceName = null,
                operatorValue = null,
                operatorNote = null,
                sendState = SendState.SENDING,
                retryCount = 0,
                lastError = null,
                sentAt = null,
            )

            val unusedPort = findUnusedPort()
            val sender = HttpSender("http://127.0.0.1:$unusedPort", validToken)
            val result = sender.send(item)

            assertTrue(result.isFailure)
        } finally {
            imageFile.delete()
        }
    }

    @Test
    fun sendReturnsFailureWhenImageFileDoesNotExist() = runTest {
        val item = QueueItem(
            localId = "local-missing",
            imagePath = "/non/existent/path/image.jpg",
            capturedAt = "2026-10-21T10:00:00Z",
            deviceName = null,
            operatorValue = null,
            operatorNote = null,
            sendState = SendState.SENDING,
            retryCount = 0,
            lastError = null,
            sentAt = null,
        )

        val sender = HttpSender("http://127.0.0.1:$serverPort", validToken)
        val result = sender.send(item)

        assertTrue(result.isFailure)
    }

    private fun findUnusedPort(): Int {
        val socket = ServerSocket(0)
        val port = socket.localPort
        socket.close()
        return port
    }

    @Test
    fun uploadClassifiesHttpResponses() = runTest {
        val image = File.createTempFile("http-status-", ".jpg").apply { writeText("image") }
        try {
            val item = QueueItem("status", image.path, "2026-11-06T00:00:00Z", null,
                null, null, SendState.SENDING, 0, null, null)
            val sender = HttpSender("http://127.0.0.1:$serverPort", validToken)
            for (code in listOf(200, 201, 204, 400, 413, 401, 403, 404, 503)) {
                uploadStatus = "$code Test"
                val result = sender.send(item)
                if (code in 200..299) {
                    assertTrue("HTTP $code", result.isSuccess)
                } else {
                    assertEquals("HTTP $code", code == 400 || code == 413,
                        result.exceptionOrNull() is PermanentSendException)
                    assertTrue(result.exceptionOrNull()?.message.orEmpty().contains("HTTP $code"))
                }
            }
        } finally {
            image.delete()
        }
    }

    @Test fun postManifestSendsJsonAndToken() = runTest {
        val json = """{"v":1,"inspection_name":"点検"}"""
        val reply = HttpSender("http://127.0.0.1:$serverPort", validToken).postManifest("I-1", json)
        assertTrue(reply.isSuccess)
        assertEquals("POST /inspections/I-1/manifest HTTP/1.1", lastRequestLine)
        assertEquals(json, manifestBody); assertEquals(validToken, manifestToken)
        assertEquals("application/json; charset=utf-8", manifestContentType)
    }
    @Test fun postManifestParsesReply() = runTest {
        manifestResponse = """{"ok":true,"matched":2,"missing_photos":["b.jpg"]}"""
        assertEquals(jp.sotuken.metercapture.inspection.ManifestReply(2, listOf("b.jpg")), HttpSender("http://127.0.0.1:$serverPort", validToken).postManifest("I-1", "{}").getOrThrow())
    }
    @Test fun postManifest404IsTemporaryWithUpdateMessage() = runTest {
        uploadStatus = "404 Not Found"
        val error = HttpSender("http://127.0.0.1:$serverPort", validToken).postManifest("I-1", "{}").exceptionOrNull()
        assertTrue(error is TemporarySendException); assertTrue(error!!.message!!.contains("PCのアプリを更新"))
    }
    @Test fun postManifestRejectsInvalidInspectionId() = runTest {
        assertTrue(HttpSender("http://127.0.0.1:$serverPort", validToken).postManifest("../x", "{}").exceptionOrNull() is PermanentSendException)
        assertEquals(null, lastRequestLine)
    }
    @Test fun postManifestRejectsInvalidOrOversizedReply() = runTest {
        val sender = HttpSender("http://127.0.0.1:$serverPort", validToken)
        for (body in listOf("{}", "x".repeat(65_537))) {
            manifestResponse = body
            assertTrue(sender.postManifest("I-1", "{}").exceptionOrNull() is TemporarySendException)
        }
        for (code in listOf(400, 409, 413)) {
            uploadStatus = "$code Error"
            assertTrue(sender.postManifest("I-1", "{}").exceptionOrNull() is PermanentSendException)
        }
    }
    @Test fun upload409IsPermanent() = runTest {
        uploadStatus = "409 Conflict"
        val file = File.createTempFile("conflict", ".jpg").apply { writeText("image") }
        try {
            val item = QueueItem("a", file.path, "2026-11-06T00:00:00Z", null, null, null, SendState.SENDING, 0, null, null)
            assertTrue(HttpSender("http://127.0.0.1:$serverPort", validToken).send(item).exceptionOrNull() is PermanentSendException)
        } finally { file.delete() }
    }

    @Test
    fun uploadSavedButResponseLostReturnsTemporaryIoFailure() = runTest {
        val image = File.createTempFile("http-timeout-", ".jpg").apply { writeText("saved-image") }
        try {
            loseUploadResponse = true
            val item = QueueItem("timeout", image.path, "2026-11-06T00:00:00Z", null,
                null, null, SendState.SENDING, 0, null, null)
            val result = HttpSender("http://127.0.0.1:$serverPort", validToken,
                readTimeoutMs = 100).send(item)
            assertTrue(result.exceptionOrNull() is SocketTimeoutException)
            assertEquals("saved-image", lastReceivedBody?.toString(Charsets.UTF_8))
        } finally {
            image.delete()
        }
    }
}
