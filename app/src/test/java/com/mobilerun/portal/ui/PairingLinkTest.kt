package com.mobilerun.portal.ui

import org.junit.Assert.*
import org.junit.Test

class PairingLinkTest {
    @Test fun importsEncryptedServerAndCode() {
        val value = PairingLink.parse("phoneassistant://pair?server=wss%3A%2F%2Fphone.example.com%3A8443%2Fdevice&code=12345678")
        assertEquals("wss://phone.example.com:8443/device", value.server)
        assertEquals("12345678", value.code)
    }
    @Test fun rejectsUnexpectedOrUnsafeLinks() {
        listOf(
            "phoneassistant://pair?server=ws%3A%2F%2Fphone.example.com%2Fdevice&code=12345678",
            "phoneassistant://pair?server=wss%3A%2F%2Fuser%40phone.example.com%2Fdevice&code=12345678",
            "phoneassistant://pair?server=wss%3A%2F%2Fphone.example.com%2Fother&code=12345678",
            "phoneassistant://pair?server=wss%3A%2F%2Fphone.example.com%2Fdevice&code=12345678&code=00000000",
            "phoneassistant://pair?server=wss%3A%2F%2Fphone.example.com%2Fdevice&code=123",
            "https://example.com/?code=12345678",
            "phoneassistant://user@pair?server=wss%3A%2F%2Fphone.example.com%2Fdevice&code=12345678",
            "phoneassistant://pair/extra?server=wss%3A%2F%2Fphone.example.com%2Fdevice&code=12345678",
            "phoneassistant://pair?server=wss%3A%2F%2Fphone.example.com%3A99999%2Fdevice&code=12345678"
        ).forEach { input ->
            try { PairingLink.parse(input); fail("Unexpectedly accepted $input") }
            catch (_: IllegalArgumentException) { }
        }
    }
}
