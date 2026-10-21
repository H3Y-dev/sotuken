package jp.sotuken.metercapture.settings

import android.content.Context
import android.content.SharedPreferences

class ReceiverSettings(
    private val prefs: SharedPreferences,
) {
    constructor(context: Context) : this(
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE),
    )

    fun getUrl(): String? = prefs.getString(KEY_URL, null)

    fun getToken(): String? = prefs.getString(KEY_TOKEN, null)

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
    }
}
