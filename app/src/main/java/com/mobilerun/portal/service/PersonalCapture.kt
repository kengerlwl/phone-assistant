package com.mobilerun.portal.service

import android.accessibilityservice.AccessibilityService
import android.graphics.Bitmap
import android.os.SystemClock
import android.util.Base64
import android.view.Display
import android.view.WindowManager
import com.mobilerun.portal.api.ApiResponse
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.CompletableFuture
import java.util.concurrent.Executors
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit
import kotlin.math.max
import kotlin.math.roundToInt

/** On-device crop/compression with explicit coordinate mapping; never captures secure windows. */
object PersonalCapture {
    private val executor = Executors.newSingleThreadExecutor()
    private val captureSlot = Semaphore(1)

    fun capture(params: JSONObject): ApiResponse {
        val service = MobilerunAccessibilityService.getInstance()
            ?: return ApiResponse.Error("Accessibility service not ready")
        val edge = params.optInt("maxEdge", 1600)
        val quality = params.optInt("quality", 85)
        val format = params.optString("format", "jpeg")
        if (edge !in 0..4096 || (edge != 0 && edge < 320) || quality !in 30..100 || format !in setOf("jpeg", "png")) {
            return ApiResponse.Error("Invalid capture options")
        }
        if (!captureSlot.tryAcquire()) return ApiResponse.Error("Capture busy; read again later")
        val result = CompletableFuture<ApiResponse>()
        val started = SystemClock.elapsedRealtime()
        val rotation = service.getSystemService(WindowManager::class.java).defaultDisplay.rotation
        try {
            service.takeScreenshot(Display.DEFAULT_DISPLAY, executor, object : AccessibilityService.TakeScreenshotCallback {
                override fun onSuccess(frame: AccessibilityService.ScreenshotResult) {
                    var source: Bitmap? = null
                    var cropped: Bitmap? = null
                    var scaled: Bitmap? = null
                    try {
                        if (result.isCancelled) return
                        val hardware = Bitmap.wrapHardwareBuffer(frame.hardwareBuffer, frame.colorSpace)
                            ?: throw IllegalStateException("No screenshot bitmap")
                        source = hardware.copy(Bitmap.Config.ARGB_8888, false)
                        hardware.recycle()
                        val bitmap = source ?: throw IllegalStateException("Cannot copy screenshot")
                        val crop = params.optJSONObject("crop")
                        val x = crop?.getInt("x") ?: 0
                        val y = crop?.getInt("y") ?: 0
                        val width = crop?.getInt("width") ?: bitmap.width
                        val height = crop?.getInt("height") ?: bitmap.height
                        require(x >= 0 && y >= 0 && width > 0 && height > 0 &&
                            x.toLong() + width <= bitmap.width && y.toLong() + height <= bitmap.height) { "Crop outside screen" }
                        cropped = Bitmap.createBitmap(bitmap, x, y, width, height)
                        val ratio = if (edge == 0) 1.0 else minOf(1.0, edge.toDouble() / max(width, height))
                        val outWidth = max(1, (width * ratio).roundToInt())
                        val outHeight = max(1, (height * ratio).roundToInt())
                        scaled = Bitmap.createScaledBitmap(cropped!!, outWidth, outHeight, true)
                        val currentRotation = service.getSystemService(WindowManager::class.java).defaultDisplay.rotation
                        check(currentRotation == rotation) { "Display rotated during capture; retry observation" }
                        val bytes = ByteArrayOutputStream().use { out ->
                            check(scaled!!.compress(if (format == "png") Bitmap.CompressFormat.PNG else Bitmap.CompressFormat.JPEG, quality, out))
                            out.toByteArray()
                        }
                        check(bytes.size <= 8 * 1024 * 1024) { "Screenshot exceeds 8 MiB; lower maxEdge" }
                        result.complete(ApiResponse.RawObject(JSONObject()
                            .put("mimeType", if (format == "png") "image/png" else "image/jpeg")
                            .put("image", Base64.encodeToString(bytes, Base64.NO_WRAP))
                            .put("width", outWidth).put("height", outHeight)
                            .put("deviceWidth", bitmap.width).put("deviceHeight", bitmap.height)
                            .put("offsetX", x).put("offsetY", y)
                            .put("scaleX", width.toDouble() / outWidth).put("scaleY", height.toDouble() / outHeight)
                            .put("rotation", rotation).put("bytes", bytes.size)
                            .put("capturedAt", System.currentTimeMillis())
                            .put("elapsedMs", SystemClock.elapsedRealtime() - started)))
                    } catch (e: Exception) {
                        result.complete(ApiResponse.Error(e.message ?: "Screenshot failed"))
                    } finally {
                        if (scaled != null && scaled !== cropped && scaled !== source) scaled?.recycle()
                        if (cropped != null && cropped !== source) cropped?.recycle()
                        source?.recycle()
                        frame.hardwareBuffer.close()
                        captureSlot.release()
                    }
                }
                override fun onFailure(errorCode: Int) {
                    result.complete(ApiResponse.Error("Screenshot denied/unavailable (code=$errorCode); secure windows are not bypassed"))
                    captureSlot.release()
                }
            })
        } catch (e: Exception) {
            captureSlot.release()
            return ApiResponse.Error(e.message ?: "Screenshot unavailable")
        }
        return try { result.get(6, TimeUnit.SECONDS) } catch (_: Exception) {
            result.cancel(false)
            ApiResponse.Error("Screenshot timed out; no cached image returned")
        }
    }
}
