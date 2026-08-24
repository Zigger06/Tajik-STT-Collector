package com.zigger06.tajiksttcollector.data

import java.security.SecureRandom
import java.util.Base64

object DeviceCredential {
    private const val SECRET_BYTES = 32

    fun generateSecret(random: SecureRandom = SecureRandom()): String {
        val bytes = ByteArray(SECRET_BYTES)
        random.nextBytes(bytes)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    }
}
