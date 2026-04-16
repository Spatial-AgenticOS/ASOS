package ai.feral.node

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.util.Size
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage

class QRScannerActivity : ComponentActivity() {

    companion object {
        const val RESULT_KEY = "pairing_json"
    }

    private var scanned = false
    private lateinit var previewView: PreviewView

    private val cameraPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) startCamera()
        else finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val layout = FrameLayout(this)
        layout.setBackgroundColor(Color.BLACK)

        previewView = PreviewView(this)
        layout.addView(
            previewView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )

        val label = TextView(this).apply {
            text = "Point at FERAL QR code"
            setTextColor(Color.WHITE)
            textSize = 18f
            gravity = Gravity.CENTER
        }
        val labelParams = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.WRAP_CONTENT
        ).apply { gravity = Gravity.BOTTOM; bottomMargin = 120 }
        layout.addView(label, labelParams)

        setContentView(layout)

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED
        ) {
            startCamera()
        } else {
            cameraPermission.launch(Manifest.permission.CAMERA)
        }
    }

    @OptIn(ExperimentalGetImage::class)
    private fun startCamera() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            val provider = cameraProviderFuture.get()

            val preview = Preview.Builder().build().also {
                it.surfaceProvider = previewView.surfaceProvider
            }

            val analyzer = ImageAnalysis.Builder()
                .setTargetResolution(Size(1280, 720))
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()

            val scanner = BarcodeScanning.getClient()

            analyzer.setAnalyzer(ContextCompat.getMainExecutor(this)) { imageProxy ->
                val mediaImage = imageProxy.image
                    ?: run { imageProxy.close(); return@setAnalyzer }
                val inputImage = InputImage.fromMediaImage(
                    mediaImage, imageProxy.imageInfo.rotationDegrees
                )

                scanner.process(inputImage)
                    .addOnSuccessListener { barcodes ->
                        for (barcode in barcodes) {
                            if (barcode.valueType == Barcode.TYPE_TEXT && !scanned) {
                                val raw = barcode.rawValue ?: continue
                                try {
                                    val json = org.json.JSONObject(raw)
                                    if (json.has("host") && json.has("token")) {
                                        scanned = true
                                        val result = Intent().putExtra(RESULT_KEY, raw)
                                        setResult(RESULT_OK, result)
                                        finish()
                                        return@addOnSuccessListener
                                    }
                                } catch (_: Exception) { }
                            }
                        }
                    }
                    .addOnCompleteListener { imageProxy.close() }
            }

            provider.unbindAll()
            provider.bindToLifecycle(
                this, CameraSelector.DEFAULT_BACK_CAMERA, preview, analyzer
            )
        }, ContextCompat.getMainExecutor(this))
    }
}
