package jp.sotuken.metercapture.queue.sender

import java.io.File
import jp.sotuken.metercapture.queue.QueueItem

/**
 * 未送信項目を公開フォルダへ画像と同名のサイドカーJSONで書き出す。
 * ファイル名: YYYYMMDDTHHMMSS_<localId>.<拡張子> / 同ベース名の .json（項目名はS1合意メモ参照）。
 * 途中経過を掴ませないため、一時名（.part）で書き終えてから正式名へリネームする。
 * 置く順序は JSON を先、画像を後（PC側が画像の出現を取り込み開始トリガーにするため）。
 */
class FolderSender(
    private val outputDirectory: File,
) : Sender {
    override suspend fun send(item: QueueItem): Result<Unit> = runCatching {
        outputDirectory.mkdirs()

        val baseName = SenderPayloads.buildBaseName(item)

        val jsonFile = File(outputDirectory, "$baseName.json")
        val jsonTempFile = File(outputDirectory, "$baseName.json.part")
        jsonTempFile.writeText(SenderPayloads.buildSidecarJson(item), Charsets.UTF_8)
        check(jsonTempFile.renameTo(jsonFile)) {
            "failed to finalize sidecar json for ${item.localId}"
        }

        val sourceImage = File(item.imagePath)
        val imageExtension = sourceImage.extension.ifBlank { "jpg" }
        val imageFile = File(outputDirectory, "$baseName.$imageExtension")
        val imageTempFile = File(outputDirectory, "$baseName.$imageExtension.part")
        sourceImage.copyTo(imageTempFile, overwrite = true)
        check(imageTempFile.renameTo(imageFile)) {
            "failed to finalize image for ${item.localId}"
        }
    }
}
