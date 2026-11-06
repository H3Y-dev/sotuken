package jp.sotuken.metercapture.device

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * 機器QR v1 の中身。仕様: tasks/design/QR機器ラベル仕様.md
 * PC側 manager/qr_label.py の parse_payload と同じ規則で判定する。
 */
data class DeviceQr(
    val id: String,
    val name: String,
    val unit: String? = null,
    val min: Double? = null,
    val max: Double? = null,
)

private val DEVICE_ID_PATTERN = Regex("[A-Za-z0-9._-]{1,32}")
private const val DEVICE_NAME_MAX = 64

/** QRの文字列を検証して返す。機器QRでない・壊れている場合は null（例外は出さない）。 */
fun parseDeviceQr(text: String): DeviceQr? {
    val data = try {
        Json.parseToJsonElement(text) as? JsonObject
    } catch (_: Exception) {
        null
    } ?: return null

    if (!isNumberEqualToOne(data["v"])) return null

    val id = (data["id"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
    if (!DEVICE_ID_PATTERN.matches(id)) return null

    val rawName = (data["name"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
    if (hasControlCharacter(rawName)) return null
    val name = rawName.trim { it.isWhitespace() }
    if (name.isEmpty() || name.codePointCount(0, name.length) > DEVICE_NAME_MAX) return null

    val unit = (data["unit"] as? JsonPrimitive)?.takeIf { it.isString }?.content
    return DeviceQr(id, name, unit, numberOrNull(data["min"]), numberOrNull(data["max"]))
}

// Pythonの `v != 1 or isinstance(v, bool)` と同じ: 文字列・真偽値は不可、数値として1に等しければ可。
private fun isNumberEqualToOne(element: Any?): Boolean = numberOrNull(element) == 1.0

private fun numberOrNull(element: Any?): Double? {
    val primitive = element as? JsonPrimitive ?: return null
    if (primitive.isString) return null
    return primitive.content.toDoubleOrNull()
}

// Pythonの unicodedata.category(c).startswith("C")（Cc/Cf/Cs/Co/Cn）に相当。
private fun hasControlCharacter(text: String): Boolean {
    var index = 0
    while (index < text.length) {
        val codePoint = text.codePointAt(index)
        when (Character.getType(codePoint).toByte()) {
            Character.CONTROL, Character.FORMAT, Character.SURROGATE,
            Character.PRIVATE_USE, Character.UNASSIGNED -> return true
        }
        index += Character.charCount(codePoint)
    }
    return false
}