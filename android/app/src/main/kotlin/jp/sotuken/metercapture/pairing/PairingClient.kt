package jp.sotuken.metercapture.pairing

import java.net.HttpURLConnection
import java.net.URL
import java.io.ByteArrayOutputStream
import jp.sotuken.metercapture.settings.ReceiverSettings
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

class PairingClient(
    private val connectTimeoutMs: Int = 2000,
    private val readTimeoutMs: Int = 3000,
    private val openConnection: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection },
) {
    suspend fun register(invitation: PairingInvitation, settings: ReceiverSettings) {
        val receiver = exchange(invitation)
        currentCoroutineContext().ensureActive()
        settings.savePaired(receiver)
    }

    suspend fun exchange(invitation: PairingInvitation): PairedReceiver = withContext(Dispatchers.IO) {
        val connection = openConnection(URL("${pairingUrl(invitation.url)}/pair"))
        try {
            val body = buildJsonObject { put("token", JsonPrimitive(invitation.token)) }
                .toString().toByteArray(Charsets.UTF_8)
            connection.apply {
                requestMethod = "POST"
                instanceFollowRedirects = false
                connectTimeout = connectTimeoutMs
                readTimeout = readTimeoutMs
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                setFixedLengthStreamingMode(body.size)
            }
            connection.outputStream.use { it.write(body) }
            when (connection.responseCode) {
                200 -> Unit
                403 -> throw PairingException("QRが無効・期限切れ・使用済みです。PCでQRを表示し直してください")
                else -> throw PairingException("PCに登録できませんでした。PCでQRを表示し直してください")
            }
            val bytes = connection.inputStream.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(1024)
                while (output.size() <= 4096) {
                    val count = input.read(buffer, 0, minOf(buffer.size, 4097 - output.size()))
                    if (count < 0) break
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            }
            if (bytes.size > 4096) throw PairingException("PCの応答が大きすぎます")
            val json = pairingJson(bytes.toString(Charsets.UTF_8))
            val id = receiverId(text(json, "receiver_id"))
            val url = pairingUrl(text(json, "url"))
            if (id != invitation.receiverId || url != invitation.url) {
                throw PairingException("QRとPCの応答が一致しません。PCでQRを表示し直してください")
            }
            PairedReceiver(url, text(json, "token"), id, pcName(text(json, "pc_name")))
        } catch (error: PairingException) {
            currentCoroutineContext().ensureActive()
            throw error
        } catch (_: Exception) {
            currentCoroutineContext().ensureActive()
            throw PairingException("PCと通信できませんでした。接続を確認し、PCでQRを表示し直してください")
        } finally {
            connection.disconnect()
        }
    }
}
