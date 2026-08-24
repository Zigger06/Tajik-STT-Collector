package com.zigger06.tajiksttcollector.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class DeviceCredentialTest {
    @Test
    fun generatedSecretsAre256BitUrlSafeAndDifferent() {
        val first = DeviceCredential.generateSecret()
        val second = DeviceCredential.generateSecret()

        assertNotEquals(first, second)
        assertEquals(32, Base64.getUrlDecoder().decode(first).size)
        assertTrue(first.matches(Regex("[A-Za-z0-9_-]+")))
    }

    @Test
    fun appSettingsToStringRedactsSecret() {
        val secret = DeviceCredential.generateSecret()
        val settings = AppSettings(
            volunteerId = "00000000-0000-0000-0000-000000000001",
            deviceSecret = secret,
            displayName = "Tester",
            region = "",
            dialect = "",
            serverUrl = "https://example.ts.net",
            consent = true,
        )

        assertFalse(settings.toString().contains(secret))
        assertTrue(settings.toString().contains("<redacted>"))
    }
}
