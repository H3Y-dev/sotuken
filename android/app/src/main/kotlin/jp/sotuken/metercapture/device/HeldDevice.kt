package jp.sotuken.metercapture.device

import jp.sotuken.metercapture.queue.QueueItem

/** 機器QRで確定して、アプリが保持している機器。name は確定時に機器名欄へ入れた値。 */
data class HeldDevice(val id: String, val name: String)

fun HeldDevice.label(): String = "機器ID: $id(QR)"

private fun normalize(input: String): String = input.trim()

/** 機器名欄を書き換えたとき、QRで入れた名前と違えば機器IDを外す（手入力扱い）。 */
fun heldDeviceAfterNameEdit(held: HeldDevice?, newName: String): HeldDevice? =
    held?.takeIf { normalize(newName) == it.name }

/** 撮影時に写真へ付ける機器ID。機器名欄が保持中の機器の名前と違えば付けない。 */
fun deviceIdForCapture(held: HeldDevice?, nameInput: String): String? =
    heldDeviceAfterNameEdit(held, nameInput)?.id

/** 撮影時の deviceIdSource。機器IDを付けるときだけ "qr"。 */
fun deviceIdSourceForCapture(held: HeldDevice?, nameInput: String): String? =
    deviceIdForCapture(held, nameInput)?.let { QueueItem.DEVICE_ID_SOURCE_QR }