package jp.sotuken.metercapture.ui

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage

/**
 * QRを1枚撮影して読み取る小さな部品（ML Kit同梱型、カメラ権限の扱いは PairingScreen と同じ）。
 * 読み取れたQRの文字列を [onCodes] へ渡す（QRが無ければ空リスト）。読み取りの失敗は [onError]。
 */
@Composable
internal fun ColumnScope.QrScanPanel(
    onCodes: (List<String>) -> Unit,
    onError: (String) -> Unit,
) {
    val context = LocalContext.current
    var reading by remember { mutableStateOf(false) }
    var active by remember { mutableStateOf(true) }
    var hasPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        hasPermission = it
    }
    val scanner = remember {
        BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
    }
    DisposableEffect(scanner) {
        onDispose { active = false; scanner.close() }
    }

    if (reading) {
        Text("QRを読み取り中…")
    } else if (hasPermission) {
        CameraCapturePanel(
            temporaryCapture = true,
            onSaved = { captured ->
                if (!active) {
                    captured.file.delete()
                } else {
                    reading = true
                    try {
                        val image = InputImage.fromFilePath(context, Uri.fromFile(captured.file))
                        scanner.process(image)
                            .addOnSuccessListener { codes ->
                                if (active) onCodes(codes.mapNotNull { it.rawValue })
                            }
                            .addOnFailureListener { if (active) onError("QRを読み取れませんでした。撮影し直してください") }
                            .addOnCompleteListener { captured.file.delete(); if (active) reading = false }
                    } catch (_: Exception) {
                        captured.file.delete()
                        reading = false
                        onError("QRを読み取れませんでした。撮影し直してください")
                    }
                }
            },
            onError = { onError("カメラを利用できません。権限を確認し、もう一度お試しください") },
        )
    } else {
        Button(onClick = { permission.launch(Manifest.permission.CAMERA) }) { Text("カメラを許可") }
    }
}