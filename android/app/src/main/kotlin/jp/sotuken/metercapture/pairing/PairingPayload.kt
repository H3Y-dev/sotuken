package jp.sotuken.metercapture.pairing

import java.net.URI
import java.util.UUID
import jp.sotuken.metercapture.settings.PrivateIpv4Validator
import kotlinx.serialization.json.*

class PairingException(message: String) : Exception(message)

// Credentials deliberately have no generated toString/copy/component methods.
class PairingInvitation(
    val url: String,
    val token: String,
    val receiverId: String,
    val pcName: String,
    val expiresAt: Long,
)

class PairedReceiver(val url: String, val token: String, val receiverId: String, val pcName: String)

fun shouldEnqueueSendOnPairing(pendingCount: Int): Boolean = pendingCount > 0

fun parsePairingQr(raw: String): PairingInvitation {
    if (raw.toByteArray(Charsets.UTF_8).size > 2048) throw PairingException("QRが大きすぎます")
    if (!raw.startsWith("SOTUKEN-PAIR:")) throw PairingException("送信先登録用のQRを読み取ってください")
    val json = pairingJson(raw.removePrefix("SOTUKEN-PAIR:"))
    if (integer(json, "v") != 1L) throw PairingException("このQRのバージョンには対応していません")
    if (text(json, "kind") != "receiver-pair") throw PairingException("送信先登録用のQRではありません")
    return PairingInvitation(
        pairingUrl(text(json, "url")), text(json, "token"),
        receiverId(text(json, "receiver_id")), pcName(text(json, "pc_name")),
        integer(json, "expires_at"),
    )
}

internal fun pairingJson(raw: String): JsonObject = try {
    Json.parseToJsonElement(raw) as? JsonObject ?: throw IllegalArgumentException()
} catch (_: Exception) {
    throw PairingException("登録データのJSONが正しくありません")
}

internal fun text(json: JsonObject, key: String): String {
    val value = json[key] as? JsonPrimitive
    if (value == null || !value.isString || value.content.isBlank()) {
        throw PairingException("登録データの項目が正しくありません")
    }
    return value.content
}

private fun integer(json: JsonObject, key: String): Long {
    val value = json[key] as? JsonPrimitive
    if (value == null || value.isString || !Regex("-?(0|[1-9][0-9]*)").matches(value.content)) {
        throw PairingException("登録データの整数項目が正しくありません")
    }
    return value.content.toLongOrNull() ?: throw PairingException("登録データの整数が範囲外です")
}

internal fun pairingUrl(raw: String): String {
    val uri = try { URI(raw) } catch (_: Exception) { throw PairingException("送信先URLが正しくありません") }
    if (uri.scheme != "http" || uri.host == null || !PrivateIpv4Validator.isPrivateIpv4Host(uri.host) ||
        uri.port !in 1..65535 || uri.rawUserInfo != null || uri.rawQuery != null ||
        uri.rawFragment != null || !uri.rawPath.isNullOrEmpty()) {
        throw PairingException("送信先にはHTTPの私用IPv4とポートを指定してください")
    }
    return raw
}

internal fun receiverId(raw: String): String {
    val parsed = try { UUID.fromString(raw) } catch (_: Exception) { throw PairingException("PC識別子が正しくありません") }
    if (!parsed.toString().equals(raw, ignoreCase = true)) throw PairingException("PC識別子が正しくありません")
    return raw
}

internal fun pcName(raw: String): String {
    if (raw.codePointCount(0, raw.length) !in 1..64 || raw.any { Character.isISOControl(it) }) {
        throw PairingException("PC名が正しくありません")
    }
    return raw
}
