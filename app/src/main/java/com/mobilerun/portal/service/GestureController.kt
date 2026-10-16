package com.mobilerun.portal.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Handler
import android.os.Looper
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** Completes only after Android reports the gesture completed; page verification is separate. */
object GestureController {
    fun tap(x: Int, y: Int): Boolean = gesture(x, y, x, y, 50)

    fun swipe(startX: Int, startY: Int, endX: Int, endY: Int, durationMs: Int = 300): Boolean =
        gesture(startX, startY, endX, endY, durationMs.coerceIn(10, 5000))

    private fun gesture(x1: Int, y1: Int, x2: Int, y2: Int, duration: Int): Boolean {
        val service = MobilerunAccessibilityService.getInstance() ?: return false
        if (Looper.myLooper() == Looper.getMainLooper()) return false
        val bounds = service.getScreenBounds()
        if (!bounds.contains(x1, y1) || !bounds.contains(x2, y2)) return false
        val latch = CountDownLatch(1)
        val completed = AtomicBoolean(false)
        val path = Path().apply {
            moveTo(x1.toFloat(), y1.toFloat())
            if (x1 != x2 || y1 != y2) lineTo(x2.toFloat(), y2.toFloat())
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, duration.toLong())).build()
        return try {
            val accepted = service.dispatchGesture(gesture, object : AccessibilityService.GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) {
                    completed.set(true)
                    latch.countDown()
                }
                override fun onCancelled(gestureDescription: GestureDescription?) { latch.countDown() }
            }, Handler(Looper.getMainLooper()))
            accepted && latch.await(duration + 2000L, TimeUnit.MILLISECONDS) && completed.get()
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        } catch (_: Exception) { false }
    }

    fun performGlobalAction(action: Int): Boolean {
        val service = MobilerunAccessibilityService.getInstance() ?: return false
        // Only back, home, recents, and notifications; no unlock/power/permission shortcuts.
        if (action !in setOf(1, 2, 3, 4)) return false
        return try { service.performGlobalAction(action) } catch (_: Exception) { false }
    }
}
