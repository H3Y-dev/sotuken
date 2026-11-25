package jp.sotuken.metercapture.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import java.io.File
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import jp.sotuken.metercapture.queue.QueueItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val THUMBNAIL_MAX_SIDE_PX = 256
private const val FULL_IMAGE_MAX_SIDE_PX = 2048

private val DISPLAY_FORMAT: DateTimeFormatter =
    DateTimeFormatter.ofPattern("yyyy/MM/dd HH:mm:ss").withZone(ZoneId.systemDefault())

/** 画像の読み込み結果。bitmap が null なら、ファイルが無い・読めないことを表す。 */
private class LoadedImage(val bitmap: Bitmap?)

@Composable
internal fun Thumbnail(
    imagePath: String,
    modifier: Modifier = Modifier,
) {
    // 画像全体は読み込まず、縮小して読む（件数が増えてもメモリを使い切らないため）。
    val loaded by produceState<LoadedImage?>(initialValue = null, imagePath) {
        value = LoadedImage(
            withContext(Dispatchers.IO) { decodeScaledBitmap(imagePath, THUMBNAIL_MAX_SIDE_PX) },
        )
    }
    val current = loaded

    Box(
        modifier = modifier.background(MaterialTheme.colorScheme.surfaceVariant),
        contentAlignment = Alignment.Center,
    ) {
        when {
            current == null -> Unit
            current.bitmap == null -> Text(
                text = "画像なし",
                style = MaterialTheme.typography.bodySmall,
            )
            else -> Image(
                bitmap = current.bitmap.asImageBitmap(),
                contentDescription = "撮影画像のサムネイル",
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

@Composable
internal fun FullImageDialog(
    item: QueueItem,
    onDismiss: () -> Unit,
    currentReceiverId: String?,
    isSendable: (QueueItem) -> Boolean = { true },
) {
    val loaded by produceState<LoadedImage?>(initialValue = null, item.imagePath) {
        value = LoadedImage(
            withContext(Dispatchers.IO) { decodeScaledBitmap(item.imagePath, FULL_IMAGE_MAX_SIDE_PX) },
        )
    }
    val current = loaded

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .clickable(onClick = onDismiss),
            color = Color.Black,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .systemBarsPadding(),
                contentAlignment = Alignment.Center,
            ) {
                when {
                    current == null -> Text("読み込み中...", color = Color.White)
                    current.bitmap == null -> Text("画像を開けません", color = Color.White)
                    else -> Image(
                        bitmap = current.bitmap.asImageBitmap(),
                        contentDescription = "撮影画像",
                        contentScale = ContentScale.Fit,
                        modifier = Modifier.fillMaxSize(),
                    )
                }
                Column(
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .padding(16.dp),
                ) {
                    Text(formatCapturedAt(item.capturedAt), color = Color.White)
                    Text(
                        text = item.deviceName?.takeIf { it.isNotBlank() } ?: "機器名なし",
                        color = Color.White,
                    )
                    Text(
                        text = "${sendStatusLabel(item, currentReceiverId, isSendable)}（タップで閉じる）",
                        color = Color.White,
                    )
                }
            }
        }
    }
}

internal fun parseInstantOrNull(iso: String): Instant? = try {
    Instant.parse(iso)
} catch (_: Exception) {
    null
}

internal fun formatCapturedAt(iso: String): String {
    val instant = parseInstantOrNull(iso) ?: return iso
    return DISPLAY_FORMAT.format(instant)
}

/**
 * 画像を、長辺が maxSidePx を下回らない範囲で縮小して読む。ファイルが無い・読めない場合は null。
 * EXIF の向き情報があれば、その分だけ回転して返す。
 */
private fun decodeScaledBitmap(path: String, maxSidePx: Int): Bitmap? {
    if (!File(path).exists()) return null

    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(path, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

    var sampleSize = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / (sampleSize * 2) >= maxSidePx) {
        sampleSize *= 2
    }
    val options = BitmapFactory.Options().apply { inSampleSize = sampleSize }
    val decoded = BitmapFactory.decodeFile(path, options) ?: return null

    val rotation = exifRotationDegrees(path)
    if (rotation == 0) return decoded
    val matrix = Matrix().apply { postRotate(rotation.toFloat()) }
    return Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
}

private fun exifRotationDegrees(path: String): Int = try {
    when (
        ExifInterface(path).getAttributeInt(
            ExifInterface.TAG_ORIENTATION,
            ExifInterface.ORIENTATION_NORMAL,
        )
    ) {
        ExifInterface.ORIENTATION_ROTATE_90 -> 90
        ExifInterface.ORIENTATION_ROTATE_180 -> 180
        ExifInterface.ORIENTATION_ROTATE_270 -> 270
        else -> 0
    }
} catch (_: Exception) {
    0
}
