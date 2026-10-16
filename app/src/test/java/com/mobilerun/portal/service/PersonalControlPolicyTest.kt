package com.mobilerun.portal.service

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class PersonalControlPolicyTest {
    @Test fun missingCoordinatesNeverBecomeZeroTaps() {
        assertNotNull(PersonalControlPolicy.validate("tap", JSONObject()))
        assertNotNull(PersonalControlPolicy.validate("tap", JSONObject().put("x", -1).put("y", 10)))
        assertNotNull(PersonalControlPolicy.validate("tap", JSONObject().put("x", 1.5).put("y", 10)))
        assertNull(PersonalControlPolicy.validate("tap", JSONObject().put("x", 0).put("y", 10)))
    }
    @Test fun broaderUpstreamCapabilitiesAreDisabled() {
        listOf("files/download", "install", "stream/start", "triggers/rules/save", "clipboard/get", "socket_port").forEach {
            assertNotNull(PersonalControlPolicy.validate(it, JSONObject()))
        }
    }
    @Test fun globalAndKeysAreRestricted() {
        assertNotNull(PersonalControlPolicy.validate("global", JSONObject().put("action", 8)))
        assertNull(PersonalControlPolicy.validate("global", JSONObject().put("action", 1)))
        assertNotNull(PersonalControlPolicy.validate("keyboard/key", JSONObject().put("key_code", 26)))
        assertNotNull(PersonalControlPolicy.validate("app", JSONObject().put("activity", "hidden.Activity")))
    }
    @Test fun observationAndNormalInputRemainAvailable() {
        assertNull(PersonalControlPolicy.validate("state", JSONObject()))
        assertNull(PersonalControlPolicy.validate("capture", JSONObject()))
        assertNull(PersonalControlPolicy.validate("keyboard/input", JSONObject().put("base64_text", "YWJj")))
    }
}
