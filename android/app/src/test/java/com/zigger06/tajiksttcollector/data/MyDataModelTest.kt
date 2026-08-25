package com.zigger06.tajiksttcollector.data

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MyDataModelTest {
    private fun settings(revoked: Boolean) = AppSettings(
        volunteerId = "00000000-0000-0000-0000-000000000001",
        deviceSecret = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
        displayName = "Tester",
        region = "",
        dialect = "",
        serverUrl = "https://example.ts.net",
        consent = true,
        participationRevoked = revoked,
    )

    @Test
    fun configuredActiveVolunteerCanContribute() {
        val settings = settings(revoked = false)
        assertTrue(settings.isConfigured)
        assertTrue(settings.canContribute)
    }

    @Test
    fun revokedVolunteerCannotContributeEvenWithExistingCredential() {
        val settings = settings(revoked = true)
        assertTrue(settings.isConfigured)
        assertFalse(settings.canContribute)
    }
}
