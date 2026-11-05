package jp.sotuken.metercapture.pairing

import java.net.HttpURLConnection
import java.net.ServerSocket
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.lang.reflect.Proxy
import android.content.SharedPreferences
import jp.sotuken.metercapture.settings.ReceiverSettings
import kotlin.concurrent.thread
import kotlinx.coroutines.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class PairingClientTest {
    private val id = "a87d8c38-9186-4c32-a827-95057a1a1b36"
    private val origin = "http://192.168.1.20:8765"
    private val invitation get() = PairingInvitation(origin, "temporary", id, "検査PC", 1793920200)
    private val response get() = """{"url":"$origin","token":"shared","receiver_id":"$id","pc_name":"検査PC"}"""

    private fun withServer(status: Int = 200, body: String = response, stall: Boolean = false, requestRead: CountDownLatch? = null, check: (PairingClient) -> Unit) {
        ServerSocket(0).use { server ->
            val release = CountDownLatch(1)
            var serverError: Throwable? = null
            val worker = thread(isDaemon = true) {
                try {
                    server.accept().use { socket ->
                        socket.soTimeout = 2000
                        val input = socket.getInputStream().bufferedReader()
                        assertEquals("POST /pair HTTP/1.1", input.readLine())
                        val headers = mutableListOf<String>()
                        while (true) {
                            val line = input.readLine() ?: error("Incomplete request")
                            if (line.isEmpty()) break
                            headers.add(line)
                        }
                        assertFalse(headers.any { it.startsWith("X-Sotuken-Token:", true) })
                        assertTrue(headers.any { it.equals("Content-Type: application/json", true) })
                        val size = headers.single { it.startsWith("Content-Length:", true) }.substringAfter(':').trim().toInt()
                        val request = CharArray(size)
                        var offset = 0
                        while (offset < size) {
                            val count = input.read(request, offset, size - offset)
                            check(count > 0)
                            offset += count
                        }
                        assertEquals("""{"token":"temporary"}""", String(request))
                        requestRead?.countDown()
                        if (stall) release.await(3, TimeUnit.SECONDS) else {
                            val bytes = body.toByteArray(Charsets.UTF_8)
                            socket.getOutputStream().use {
                                it.write(("HTTP/1.1 $status Test\r\nContent-Length: ${bytes.size}\r\n" +
                                    "Location: http://127.0.0.1:${server.localPort}/other\r\nConnection: close\r\n\r\n").toByteArray())
                                it.write(bytes)
                            }
                        }
                    }
                } catch (failure: Throwable) { serverError = failure }
            }
            try {
                check(PairingClient(readTimeoutMs = if (stall) 100 else 2000, openConnection = { requested ->
                    assertEquals("$origin/pair", requested.toString())
                    URL("http://127.0.0.1:${server.localPort}/pair").openConnection() as HttpURLConnection
                }))
            } finally {
                release.countDown()
                server.close()
                worker.join(4000)
                assertFalse(worker.isAlive)
                serverError?.let { throw AssertionError("Mock server failed", it) }
            }
        }
    }

    @Test fun exchangesTokenAndChecksRequest() = withServer { client ->
        val value = runBlocking { client.exchange(invitation) }
        assertEquals("shared", value.token)
        assertEquals(id, value.receiverId)
        assertEquals(origin, value.url)
        assertEquals("検査PC", value.pcName)
    }

    @Test fun rejectsForbiddenWithoutDisplayingResponseSecrets() = withServer(403, "server-secret") { client ->
        val error = assertThrows(PairingException::class.java) { runBlocking { client.exchange(invitation) } }
        assertTrue(error.message.orEmpty().contains("QR"))
        assertFalse(error.message.orEmpty().contains("server-secret"))
    }

    @Test fun rejectsDifferentReceiver() = withServer(body = response.replace(id, "32eefc8c-b30b-4a82-af20-084f62a78c75")) { client ->
        assertThrows(PairingException::class.java) { runBlocking { client.exchange(invitation) } }
    }

    @Test fun rejectsDifferentUrl() = withServer(body = response.replace(origin, "http://10.0.0.2:80")) { client ->
        assertThrows(PairingException::class.java) { runBlocking { client.exchange(invitation) } }
    }

    @Test fun timesOutWithoutLeakingDetails() = withServer(stall = true) { client ->
        val error = assertThrows(PairingException::class.java) { runBlocking { client.exchange(invitation) } }
        assertFalse(error.message.orEmpty().contains("temporary"))
    }

    @Test fun doesNotFollowRedirect() = withServer(302) { client ->
        assertThrows(PairingException::class.java) { runBlocking { client.exchange(invitation) } }
    }

    @Test fun rejectsOversizedResponse() = withServer(body = "x".repeat(4097)) { client ->
        assertThrows(PairingException::class.java) { runBlocking { client.exchange(invitation) } }
    }

    @Test fun rejectsBrokenResponse() = withServer(body = "{broken") { client ->
        assertThrows(PairingException::class.java) { runBlocking { client.exchange(invitation) } }
    }

    @Test fun rejectsEmptyToken() = withServer(body = response.replace("shared", "")) { client ->
        assertThrows(PairingException::class.java) { runBlocking { client.exchange(invitation) } }
    }

    private fun untouchedSettings(): ReceiverSettings {
        val prefs = Proxy.newProxyInstance(SharedPreferences::class.java.classLoader, arrayOf(SharedPreferences::class.java)) { _, _, _ ->
            throw AssertionError("Failed/cancelled registration must not access old settings")
        } as SharedPreferences
        return ReceiverSettings(prefs)
    }

    @Test fun failedExchangeDoesNotTouchSettings() = withServer(403) { client ->
        assertThrows(PairingException::class.java) { runBlocking { client.register(invitation, untouchedSettings()) } }
    }

    @Test fun mismatchedExchangeDoesNotTouchSettings() = withServer(body = response.replace(id, "32eefc8c-b30b-4a82-af20-084f62a78c75")) { client ->
        assertThrows(PairingException::class.java) { runBlocking { client.register(invitation, untouchedSettings()) } }
    }

    @Test fun cancelledExchangeDoesNotTouchSettings() {
        val read = CountDownLatch(1)
        withServer(stall = true, requestRead = read) { client ->
            runBlocking {
                val job = launch { client.register(invitation, untouchedSettings()) }
                val received = withContext(Dispatchers.IO) { read.await(2, TimeUnit.SECONDS) }
                assertTrue(received)
                job.cancelAndJoin()
            }
        }
    }
}
