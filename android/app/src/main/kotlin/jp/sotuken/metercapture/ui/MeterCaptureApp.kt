package jp.sotuken.metercapture.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import jp.sotuken.metercapture.capture.CapturedImage
import jp.sotuken.metercapture.queue.CaptureMeta
import jp.sotuken.metercapture.queue.QueueStore
import kotlinx.coroutines.launch

@Composable
fun MeterCaptureApp(queueStore: QueueStore) {
    val context = LocalContext.current
    val queueItems by queueStore.observeQueue().collectAsStateWithLifecycle(initialValue = emptyList())
    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    var capturedImage by remember { mutableStateOf<CapturedImage?>(null) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    val coroutineScope = rememberCoroutineScope()
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        hasCameraPermission = granted
    }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        hasCameraPermission =
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
    }

    MaterialTheme {
        Scaffold { innerPadding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding)
                    .padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(text = "メーター撮影", style = MaterialTheme.typography.headlineMedium)
                Text(text = "キュー: ${queueItems.size}件")

                if (hasCameraPermission) {
                    CameraCapturePanel(
                        onSaved = { image ->
                            coroutineScope.launch {
                                try {
                                    queueStore.enqueue(
                                        imageFile = image.file,
                                        meta = CaptureMeta(
                                            deviceName = null,
                                            operatorValue = null,
                                            operatorNote = null,
                                        ),
                                    )
                                    capturedImage = image
                                    errorMessage = null
                                } catch (error: Exception) {
                                    capturedImage = null
                                    errorMessage = "キューへの追加に失敗しました: ${error.message ?: error}"
                                }
                            }
                        },
                        onError = {
                            capturedImage = null
                            errorMessage = it
                        },
                    )
                } else {
                    Text("カメラの使用を許可してください")
                    Button(onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) }) {
                        Text("許可")
                    }
                }

                capturedImage?.let { Text("キューに追加しました: ${it.file.name}") }
                errorMessage?.let {
                    Text(text = it, color = MaterialTheme.colorScheme.error)
                }

                // TODO(SKくん): ガイド枠・キュー一覧・入力フォームを実装する。Sprint 3
            }
        }
    }
}

