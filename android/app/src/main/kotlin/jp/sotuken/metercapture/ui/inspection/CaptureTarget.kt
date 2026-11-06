package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.device.DeviceQr
import jp.sotuken.metercapture.device.isValidDeviceId
import jp.sotuken.metercapture.device.validDeviceNameOrNull
import jp.sotuken.metercapture.inspection.RouteDevice
import jp.sotuken.metercapture.queue.CaptureMeta
import jp.sotuken.metercapture.queue.QueueItem

data class CaptureTarget(val deviceId: String?, val deviceName: String?, val source: String?)

fun CaptureTarget.toMeta(): CaptureMeta = CaptureMeta(deviceName, null, null, deviceId, source)
fun targetFromQr(qr: DeviceQr): CaptureTarget = CaptureTarget(qr.id, qr.name, "qr")
fun targetFromRoute(device: RouteDevice): CaptureTarget = CaptureTarget(device.id, device.name, "manual")
fun targetFromPhoto(item: QueueItem): CaptureTarget = CaptureTarget(item.deviceId, item.deviceName, item.deviceIdSource)

fun manualTarget(name: String, id: String): Result<CaptureTarget> = runCatching {
    val validName = requireNotNull(validDeviceNameOrNull(name)) { "機器名は1〜64文字で入力してください" }
    require(id.isEmpty() || isValidDeviceId(id)) { "機器IDは英数字と . _ - で32文字以内です" }
    CaptureTarget(id.takeIf { it.isNotEmpty() }, validName, if (id.isEmpty()) null else "manual")
}

fun initialTarget(routeDevices: List<RouteDevice>?, photos: List<QueueItem>): CaptureTarget? {
    val shotIds = photos.mapNotNull { it.deviceId }.toSet()
    return routeDevices?.firstOrNull { it.id !in shotIds }?.let(::targetFromRoute)
}

fun targetAfterCapture(routeDevices: List<RouteDevice>?, photosAfter: List<QueueItem>, captured: CaptureTarget?): CaptureTarget? =
    if (routeDevices?.any { it.id == captured?.deviceId } == true) initialTarget(routeDevices, photosAfter) else null
