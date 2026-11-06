package jp.sotuken.metercapture.settings

import android.content.Context
import android.content.SharedPreferences
import jp.sotuken.metercapture.pairing.PairedReceiver
import jp.sotuken.metercapture.pairing.pairingUrl
import jp.sotuken.metercapture.pairing.receiverId
import jp.sotuken.metercapture.pairing.pcName

class ReceiverSettings(
    private val prefs: SharedPreferences,
) {
    constructor(context: Context) : this(
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE),
    )

    fun getUrl(): String? = prefs.getString(KEY_URL, null)

    fun getToken(): String? = prefs.getString(KEY_TOKEN, null)

    fun getReceiverId(): String? = prefs.getString(KEY_RECEIVER_ID, null)

    fun getPcName(): String? = prefs.getString(KEY_PC_NAME, null)

    fun savePaired(receiver: PairedReceiver) {
        pairingUrl(receiver.url)
        receiverId(receiver.receiverId)
        pcName(receiver.pcName)
        require(receiver.token.isNotBlank()) { "登録用の合言葉が正しくありません" }
        prefs.edit()
            .putString(KEY_URL, receiver.url)
            .putString(KEY_TOKEN, receiver.token)
            .putString(KEY_RECEIVER_ID, receiver.receiverId)
            .putString(KEY_PC_NAME, receiver.pcName)
            .apply()
    }

    fun save(url: String, token: String) {
        val validation = PrivateIpv4Validator.validateUrl(url)
        require(validation is PrivateIpv4Validator.ValidationResult.Valid) {
            (validation as PrivateIpv4Validator.ValidationResult.Invalid).message
        }
        val trimmed = url.trim()
        val normalizedUrl = if (!trimmed.startsWith("http://", ignoreCase = true) &&
            !trimmed.startsWith("https://", ignoreCase = true)
        ) {
            "http://$trimmed"
        } else {
            trimmed
        }.trimEnd('/')

        prefs.edit()
            .putString(KEY_URL, normalizedUrl)
            .putString(KEY_TOKEN, token.trim())
            .remove(KEY_RECEIVER_ID)
            .remove(KEY_PC_NAME)
            .apply()
    }

    fun isConfigured(): Boolean {
        val url = getUrl()
        val token = getToken()
        return !url.isNullOrBlank() && !token.isNullOrBlank() &&
            PrivateIpv4Validator.validateUrl(url) is PrivateIpv4Validator.ValidationResult.Valid
    }

    companion object {
        const val PREFS_NAME = "receiver_settings"
        const val KEY_URL = "receiver_url"
        const val KEY_TOKEN = "receiver_token"
        const val KEY_RECEIVER_ID = "receiver_id"
        const val KEY_PC_NAME = "receiver_pc_name"
    }
}
