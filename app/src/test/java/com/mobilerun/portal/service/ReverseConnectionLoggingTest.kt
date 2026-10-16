package com.mobilerun.portal.service

import org.junit.Assert.assertTrue
import org.junit.Test

class ReverseConnectionLoggingTest {
    @Test
    fun allControlPayloadsAreRedacted() {
        listOf("clipboard/set", "clipboard/get", "keyboard/input", "state", "capture", "screenshot", "app", "app/deep-link", "unknown").forEach {
            assertTrue(shouldRedactReverseRequestPayload(it))
            assertTrue(shouldRedactReverseResponsePayload(it))
        }
    }
}
