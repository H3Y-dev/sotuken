package jp.sotuken.metercapture.ui

import android.content.Context
import android.os.Environment
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import jp.sotuken.metercapture.capture.CapturedImage
import jp.sotuken.metercapture.capture.captureFileName
import jp.sotuken.metercapture.capture.capturesDir

@Composable
internal fun ColumnScope.CameraCapturePanel(
    onSaved: (CapturedImage) -> Unit,
    onError: (String) -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var imageCapture by remember { mutableStateOf<ImageCapture?>(null) }
    var isCapturing by remember { mutableStateOf(false) }
    val previewView = remember { PreviewView(context) }
    val currentOnError by rememberUpdatedState(onError)

    DisposableEffect(lifecycleOwner, previewView) {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
        var cameraProvider: ProcessCameraProvider? = null
        var disposed = false

        cameraProviderFuture.addListener(
            {
                if (!disposed) {
                    try {
                        cameraProvider = cameraProviderFuture.get()
                        val preview = Preview.Builder().build().also {
                            it.surfaceProvider = previewView.surfaceProvider
                        }
                        val capture = ImageCapture.Builder().build()

                        cameraProvider?.unbindAll()
                        cameraProvider?.bindToLifecycle(
                            lifecycleOwner,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            capture,
                        )
                        imageCapture = capture
                    } catch (exception: Exception) {
                        currentOnError(
                            "カメラを開始できません: ${exception.message ?: "不明なエラー"}",
                        )
                    }
                }
            },
            ContextCompat.getMainExecutor(context),
        )

        onDispose {
            disposed = true
            imageCapture = null
            cameraProvider?.unbindAll()
        }
    }

    AndroidView(
        factory = { previewView },
        modifier = Modifier
            .fillMaxWidth()
            .weight(1f),
    )

    Button(
        enabled = imageCapture != null && !isCapturing,
        onClick = {
            val capture = imageCapture ?: return@Button
            isCapturing = true
            takePhoto(
                context = context,
                imageCapture = capture,
                onSaved = {
                    isCapturing = false
                    onSaved(it)
                },
                onError = {
                    isCapturing = false
                    onError(it)
                },
            )
        },
    ) {
        Text(if (isCapturing) "保存中..." else "撮影")
    }
}

private fun takePhoto(
    context: Context,
    imageCapture: ImageCapture,
    onSaved: (CapturedImage) -> Unit,
    onError: (String) -> Unit,
) {
    val capturedAtEpochMillis = System.currentTimeMillis()
    val baseDir = context.getExternalFilesDir(Environment.DIRECTORY_PICTURES)
    if (baseDir == null) {
        onError("撮影画像の保存先を利用できません")
        return
    }

    val file = try {
        capturesDir(baseDir).resolve(captureFileName(capturedAtEpochMillis))
    } catch (exception: IllegalStateException) {
        onError(exception.message ?: "撮影画像の保存先を作成できません")
        return
    }
    if (file.exists()) {
        onError("同名の撮影画像が既に存在するため保存できません: ${file.name}")
        return
    }
    val outputOptions = ImageCapture.OutputFileOptions.Builder(file).build()

    imageCapture.takePicture(
        outputOptions,
        ContextCompat.getMainExecutor(context),
        object : ImageCapture.OnImageSavedCallback {
            override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                onSaved(CapturedImage(file, capturedAtEpochMillis))
            }

            override fun onError(exception: ImageCaptureException) {
                onError("撮影に失敗しました: ${exception.message}")
            }
        },
    )
}
