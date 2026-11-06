package jp.sotuken.metercapture.settings

import android.content.Context
import android.content.SharedPreferences
import jp.sotuken.metercapture.device.HeldDevice

/** 機器QRで確定した機器を、アプリを閉じても残す置き場所。 */
class DeviceIdSettings(
    private val prefs: SharedPreferences,
) {
    constructor(context: Context) : this(
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE),
    )

    fun get(): HeldDevice? {
        val id = prefs.getString(KEY_ID, null)
        val name = prefs.getString(KEY_NAME, null)
        return if (id.isNullOrEmpty() || name.isNullOrEmpty()) null else HeldDevice(id, name)
    }

    fun save(device: HeldDevice) {
        prefs.edit()
            .putString(KEY_ID, device.id)
            .putString(KEY_NAME, device.name)
            .apply()
    }

    fun clear() {
        prefs.edit()
            .remove(KEY_ID)
            .remove(KEY_NAME)
            .apply()
    }

    companion object {
        const val PREFS_NAME = "device_id_settings"
        const val KEY_ID = "device_id"
        const val KEY_NAME = "device_name"
    }
}