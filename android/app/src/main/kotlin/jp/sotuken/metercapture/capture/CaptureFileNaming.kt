package jp.sotuken.metercapture.capture

import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

data class CapturedImage(
    val file: File,
    val capturedAtEpochMillis: Long,
)

fun captureFileName(
    epochMillis: Long,
    timeZone: TimeZone = TimeZone.getDefault(),
): String = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).apply {
    this.timeZone = timeZone
}.format(Date(epochMillis)) + ".jpg"

fun capturesDir(baseDir: File): File {
    val directory = baseDir.resolve("captures")
    check(directory.isDirectory || directory.mkdirs()) {
        "撮影画像の保存先を作成できません: ${directory.absolutePath}"
    }
    return directory
}
