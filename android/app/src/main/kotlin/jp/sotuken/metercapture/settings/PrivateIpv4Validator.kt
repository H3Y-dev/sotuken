package jp.sotuken.metercapture.settings

import java.net.URI

object PrivateIpv4Validator {

    sealed class ValidationResult {
        object Valid : ValidationResult()
        data class Invalid(val message: String) : ValidationResult()
    }

    /**
     * ホスト名がプライベートIPv4（10/8, 172.16/12, 192.168/16）かどうかを判定する。
     * ループバック（127.0.0.1）やリンクローカル、パブリックIP、ドメイン名は false を返す。
     */
    fun isPrivateIpv4Host(host: String): Boolean {
        val parts = host.trim().split('.')
        if (parts.size != 4) return false
        if (parts.any { it.isEmpty() || it.any { digit -> digit !in '0'..'9' } ||
                (it.length > 1 && it.startsWith('0')) }) return false
        val octets = parts.map { it.toIntOrNull() ?: return false }
        if (octets.any { it !in 0..255 }) return false

        val (o1, o2, _, _) = octets
        return when {
            o1 == 10 -> true
            o1 == 172 && o2 in 16..31 -> true
            o1 == 192 && o2 == 168 -> true
            else -> false
        }
    }

    /**
     * URLの検証を行う。
     * ホストがプライベートIPv4でなければ Invalid を返す。
     */
    fun validateUrl(rawUrl: String): ValidationResult {
        val trimmed = rawUrl.trim()
        if (trimmed.isEmpty()) {
            return ValidationResult.Invalid("URLを入力してください")
        }

        val urlWithScheme = if (!trimmed.startsWith("http://", ignoreCase = true) &&
            !trimmed.startsWith("https://", ignoreCase = true)
        ) {
            "http://$trimmed"
        } else {
            trimmed
        }

        val uri = try {
            URI(urlWithScheme)
        } catch (e: Exception) {
            return ValidationResult.Invalid("URLの形式が正しくありません")
        }

        val scheme = uri.scheme?.lowercase()
        if (scheme != "http" && scheme != "https") {
            return ValidationResult.Invalid("URLのスキームは http または https を指定してください")
        }

        val host = uri.host
        if (host.isNullOrBlank()) {
            return ValidationResult.Invalid("URLに有効なホスト名が含まれていません")
        }

        if (!isPrivateIpv4Host(host)) {
            return ValidationResult.Invalid(
                "送信先URLのホスト（$host）はプライベートIPv4（10/8, 172.16/12, 192.168/16）を指定してください",
            )
        }

        return ValidationResult.Valid
    }
}
