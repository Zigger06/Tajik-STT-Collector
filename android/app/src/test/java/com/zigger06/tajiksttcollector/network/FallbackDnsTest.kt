package com.zigger06.tajiksttcollector.network

import okhttp3.Dns
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Test
import java.net.InetAddress
import java.net.UnknownHostException

class FallbackDnsTest {
    private fun dns(block: (String) -> List<InetAddress>): Dns = object : Dns {
        override fun lookup(hostname: String): List<InetAddress> = block(hostname)
    }

    @Test
    fun `uses system result without touching fallback`() {
        val expected = InetAddress.getByName("203.0.113.10")
        var fallbackCalled = false
        val resolver = FallbackDns(
            primary = dns { listOf(expected) },
            fallback = dns {
                fallbackCalled = true
                listOf(InetAddress.getByName("203.0.113.11"))
            },
        )

        assertEquals(listOf(expected), resolver.lookup("example.test"))
        assertFalse(fallbackCalled)
    }

    @Test
    fun `empty primary result falls back`() {
        val expected = InetAddress.getByName("203.0.113.20")
        val resolver = FallbackDns(
            primary = dns { emptyList() },
            fallback = dns { listOf(expected) },
        )

        assertEquals(listOf(expected), resolver.lookup("example.test"))
    }

    @Test
    fun `primary exception falls back`() {
        val expected = InetAddress.getByName("203.0.113.30")
        val resolver = FallbackDns(
            primary = dns { throw UnknownHostException("system failed") },
            fallback = dns { listOf(expected) },
        )

        assertEquals(listOf(expected), resolver.lookup("example.test"))
    }

    @Test
    fun `both resolvers failing produces unknown host`() {
        val resolver = FallbackDns(
            primary = dns { emptyList() },
            fallback = dns { emptyList() },
        )

        assertThrows(UnknownHostException::class.java) {
            resolver.lookup("example.test")
        }
    }
}
