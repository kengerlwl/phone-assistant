package com.mobilerun.portal.ui

import java.net.URI
import java.net.URLDecoder

/** Pairing imports only prefill UI; they never grant permissions or start a session. */
object PairingLink {
    data class Details(val server: String, val code: String)

    fun parse(value: String): Details {
        val uri = URI(value.trim())
        require(uri.scheme == "phoneassistant" && uri.host == "pair" && uri.userInfo == null && uri.port == -1 && uri.path.isNullOrEmpty() && uri.fragment == null) { "Invalid pairing link" }
        val entries = uri.rawQuery.orEmpty().split("&").map { field ->
            val pair = field.split("=", limit = 2)
            require(pair.size == 2) { "Invalid pairing data" }
            URLDecoder.decode(pair[0], "UTF-8") to URLDecoder.decode(pair[1], "UTF-8")
        }
        require(entries.size == 2 && entries.map { it.first }.toSet() == setOf("server", "code")) { "Unexpected pairing fields" }
        val fields = entries.toMap()
        val server = URI(fields.getValue("server"))
        require(server.scheme == "wss" && !server.host.isNullOrBlank() && server.userInfo == null && server.query == null && server.fragment == null && server.path == "/device" && (server.port == -1 || server.port in 1..65535)) { "Invalid encrypted server address" }
        val code = fields.getValue("code")
        require(code.matches(Regex("[0-9]{8}"))) { "Invalid pairing code" }
        return Details(server.toString(), code)
    }
}
