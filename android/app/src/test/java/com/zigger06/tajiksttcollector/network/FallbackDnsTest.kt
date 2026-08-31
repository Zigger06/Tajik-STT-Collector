package com.zigger06.tajiksttcollector.network

import okhttp3.Dns
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.net.InetAddress
import java.net.UnknownHostException

class FallbackDnsTest {
    @Test
    fun `uses system result without touching fallback`() {
        val expected = InetAddress.getByName("203.0.113.10")
        var fallbackCalled = false
        val dns = FallbackDns(
            primary = Dns { listOf(expected) },
            fallback = Dns {
                fallbackCalled = true
                listOf(InetAddress.getByName("203.0.113.11"))
            },
        )

        assertEquals(listOf(expected), dns.lookup("example.test"))
        assertEquals(false, fallbackCalled)
    }

    @Test
    fun `empty primary result falls back`() {
        val expected = InetAddress.getByName("203.0.113.20")
        val dns = FallbackDns(
            primary = Dns { emptyList() },
            fallback = Dns { listOf(expected) },
        )

        assertEquals(listOf(expected), dns.lookup("example.test"))
    }

    @Test
    fun `primary exception falls back`() {
        val expected = InetAddress.getByName("203.0.113.30")
        val dns = FallbackDns(
            primary = Dns { throw UnknownHostException("system failed") },
            fallback = Dns { listOf(expected) },
        )

        assertEquals(listOf(expected), dns.lookup("example.test"))
    }

    @Test
    fun `both resolvers failing produces unknown host`() {
        val dns = FallbackDns(
            primary = Dns { emptyList() },
            fallback = Dns { emptyList() },
        )

        assertThrows(UnknownHostException::class.java) {
            dns.lookup("example.test")
        }
    }
}
