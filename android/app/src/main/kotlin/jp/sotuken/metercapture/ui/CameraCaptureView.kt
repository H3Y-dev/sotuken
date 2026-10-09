package jp.sotuken.metercapture.ui

import android.graphics.BitmapFactory
import android.util.Log
import android.view.ViewGroup
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import java.io.File
import java.time.Instant

private const val TAG = "MeterCapture"

/**
 * 撮影結果情報。
 * 撮影日時(capturedAt: ISO 8601 UTC)と保存先ファイルパスを保持する。
 */
data class CapturedImageInfo(
    val file: File,
    val capturedAt: String,
)

@Composable
fun CameraCaptureView(
    onCaptureComplete: ((CapturedImageInfo) -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    var imageCapture by remember { mutableStateOf<ImageCapture?>(null) }
    var isCapturing by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var lastCapturedInfo by remember { mutableStateOf<CapturedImageInfo?>(null) }

    val capturedBitmap = remember(lastCapturedInfo) {
        lastCapturedInfo?.file?.let { file ->
            if (file.exists()) {
                BitmapFactory.decodeFile(file.absolutePath)
            } else null
        }
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        if (lastCapturedInfo != null) {
            val info = lastCapturedInfo!!
            // 撮影完了時の結果表示カード（保存先と日時の確認用）
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = "撮影・端末保存完了",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Text(
                        text = "撮影日時 (captured_at):\n${info.capturedAt}",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(
                        text = "保存先パス:\n${info.file.absolutePath}",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Text(
                        text = "ファイルサイズ: ${info.file.length()} bytes",
                        style = MaterialTheme.typography.bodySmall,
                    )

                    capturedBitmap?.let { bmp ->
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = "保存画像プレビュー:",
                            style = MaterialTheme.typography.labelLarge,
                        )
                        Image(
                            bitmap = bmp.asImageBitmap(),
                            contentDescription = "撮影画像プレビュー",
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(220.dp)
                                .clip(RoundedCornerShape(8.dp)),
                            contentScale = ContentScale.Fit,
                        )
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    Button(
                        onClick = {
                            lastCapturedInfo = null
                            errorMessage = null
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(text = "再撮影 / 続けて撮影")
                    }
                }
            }
        } else {
            // カメラプレビューと撮影ボタン
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(3f / 4f)
                    .clip(RoundedCornerShape(12.dp))
                    .background(Color.Black),
                contentAlignment = Alignment.Center,
            ) {
                AndroidView(
                    modifier = Modifier.fillMaxSize(),
                    factory = { ctx ->
                        val previewView = PreviewView(ctx).apply {
                            layoutParams = ViewGroup.LayoutParams(
                                ViewGroup.LayoutParams.MATCH_PARENT,
                                ViewGroup.LayoutParams.MATCH_PARENT,
                            )
                        }

                        val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)
                        cameraProviderFuture.addListener({
                            try {
                                val cameraProvider = cameraProviderFuture.get()
                                val preview = Preview.Builder().build().also {
                                    it.surfaceProvider = previewView.surfaceProvider
                                }
                                val capture = ImageCapture.Builder()
                                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                                    .build()
                                imageCapture = capture

                                cameraProvider.unbindAll()
                                cameraProvider.bindToLifecycle(
                                    lifecycleOwner,
                                    CameraSelector.DEFAULT_BACK_CAMERA,
                                    preview,
                                    capture,
                                )
                            } catch (e: Exception) {
                                Log.e(TAG, "カメラの起動に失敗しました", e)
                                errorMessage = "カメラの起動に失敗しました: ${e.localizedMessage ?: e.message}"
                            }
                        }, ContextCompat.getMainExecutor(ctx))

                        previewView
                    },
                )

                if (isCapturing) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .background(Color.Black.copy(alpha = 0.5f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            CircularProgressIndicator(color = Color.White)
                            Text(text = "保存中...", color = Color.White)
                        }
                    }
                }
            }

            if (errorMessage != null) {
                Text(
                    text = errorMessage ?: "",
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }

            Button(
                onClick = {
                    val capture = imageCapture
                    if (capture == null || isCapturing) return@Button

                    isCapturing = true
                    errorMessage = null

                    val captureFile = CaptureStorage.createCaptureFile(context)
                    val outputOptions = ImageCapture.OutputFileOptions.Builder(captureFile).build()

                    capture.takePicture(
                        outputOptions,
                        ContextCompat.getMainExecutor(context),
                        object : ImageCapture.OnImageSavedCallback {
                            override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                                val capturedAt = Instant.now().toString()
                                isCapturing = false
                                Log.i(
                                    TAG,
                                    "撮影画像を端末に保存しました: path=${captureFile.absolutePath}, capturedAt=$capturedAt, size=${captureFile.length()} bytes",
                                )
                                val info = CapturedImageInfo(
                                    file = captureFile,
                                    capturedAt = capturedAt,
                                )
                                lastCapturedInfo = info
                                onCaptureComplete?.invoke(info)
                            }

                            override fun onError(exception: ImageCaptureException) {
                                isCapturing = false
                                Log.e(TAG, "撮影エラーが発生しました", exception)
                                errorMessage = "撮影に失敗しました: ${exception.localizedMessage ?: exception.message}"
                            }
                        },
                    )
                },
                enabled = !isCapturing && imageCapture != null,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(56.dp),
            ) {
                Text(text = if (isCapturing) "保存中..." else "メーターを撮影する")
            }
        }
    }
}