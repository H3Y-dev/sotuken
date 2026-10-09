package jp.sotuken.metercapture.ui

import android.content.Context
import android.os.Environment
import java.io.File
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * 撮影画像の保存先管理。
 * 仕様書に従い、公開領域ではなくアプリ専用領域に保存し、.nomedia を置いて
 * ギャラリーやフォトアプリのメディアスキャン対象から外す。
 */
object CaptureStorage {
    private val FILE_DATE_FORMATTER: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss")
        .withZone(ZoneId.systemDefault())

    /**
     * 日時を指定してファイル名を生成する。
     */
    fun generateFileName(instant: Instant = Instant.now()): String {
        val timestamp = FILE_DATE_FORMATTER.format(instant)
        return "meter_${timestamp}.jpg"
    }

    /**
     * アプリ専用の保存先ディレクトリを取得する。
     * 存在しない場合は作成し、.nomedia ファイルを配置する。
     */
    fun getCaptureDirectory(context: Context): File {
        val baseDir = context.getExternalFilesDir(Environment.DIRECTORY_PICTURES) ?: context.filesDir
        val captureDir = File(baseDir, "captures")
        if (!captureDir.exists()) {
            captureDir.mkdirs()
        }
        val noMediaFile = File(captureDir, ".nomedia")
        if (!noMediaFile.exists()) {
            try {
                noMediaFile.createNewFile()
            } catch (_: Exception) {
                // Ignore failure to create .nomedia
            }
        }
        return captureDir
    }

    /**
     * 新規撮影用の一意なファイルを作成する。
     */
    fun createCaptureFile(context: Context, instant: Instant = Instant.now()): File {
        val dir = getCaptureDirectory(context)
        val timestamp = FILE_DATE_FORMATTER.format(instant)
        var targetFile = File(dir, "meter_${timestamp}.jpg")
        var suffix = 1
        while (targetFile.exists()) {
            targetFile = File(dir, "meter_${timestamp}_${suffix}.jpg")
            suffix++
        }
        return targetFile
    }
}