package com.mobilerun.portal.service

import org.json.JSONObject

/** Explicitly supported surface; no file access, installers, clipboard, or passive streaming. */
object PersonalControlPolicy {
    val allowed = setOf("state", "screenshot", "capture", "tap", "swipe", "global", "app", "keyboard/input", "keyboard/clear", "keyboard/key", "version", "time", "packages")

    fun validate(method: String, params: JSONObject): String? {
        if (method !in allowed) return "Method not enabled in personal edition"
        val coordinates = when (method) {
            "tap" -> listOf("x", "y")
            "swipe" -> listOf("startX", "startY", "endX", "endY")
            else -> emptyList()
        }
        if (coordinates.any { key ->
            val value = params.opt(key)
            value !is Number || value.toDouble() != value.toInt().toDouble() || value.toInt() !in 0..16384
        }) return "Missing or invalid coordinates"
        if (method == "swipe" && params.optInt("duration", 300) !in 10..5000) return "Invalid gesture duration"
        if (method == "global" && params.optInt("action", -1) !in 1..4) return "Global action not allowed"
        if (method == "app" && (params.optBoolean("stopBeforeLaunch", false) || params.has("activity"))) return "Only ordinary app launch is allowed"
        if (method == "keyboard/input" && params.optString("base64_text").length > 32768) return "Text too long"
        if (method == "keyboard/key" && params.optInt("key_code", -1) !in setOf(61, 66, 67, 112, 123, 122, 19, 20, 21, 22)) return "Key not allowed"
        return null
    }
}
