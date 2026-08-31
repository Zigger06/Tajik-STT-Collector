package com.zigger06.tajiksttcollector.network

import android.util.Log
import okhttp3.ConnectionSpec
import okhttp3.Dns
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.TlsVersion
import java.net.Inet4Address
import java.net.InetAddress
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

private const val TLS_PROBE_TAG = "TajikSTT-TLS"
private const val TLS_PROBE_URL = "https://mlscientist06.tailbc3525.ts.net/health"

/**
 * Diagnostic-only probe matrix. It runs only after the normal setup request has
 * already failed and performs unauthenticated GET /health requests. It does not
 * change production registration behavior and never sends volunteer credentials.
 */
internal object TlsDiagnosticProbe {
    private val running = AtomicBoolean(false)

    private val ipv4OnlyDns = object : Dns {
        override fun lookup(hostname: String): List<InetAddress> {
            val ipv4 = Dns.SYSTEM.lookup(hostname).filterIsInstance<Inet4Address>()
            if (ipv4.isEmpty()) throw UnknownHostException("No IPv4 address for $hostname")
            return ipv4
        }
    }

    fun runAsync() {
        if (!running.compareAndSet(false, true)) return
        Thread {
            try {
                Log.e(TLS_PROBE_TAG, "BEGIN probe matrix url=$TLS_PROBE_URL")

                runProbe(
                    "app-like",
                    baseBuilder().dns(ResilientDns).build(),
                )
                runProbe(
                    "system-default",
                    baseBuilder().build(),
                )
                runProbe(
                    "ipv4-only",
                    baseBuilder().dns(ipv4OnlyDns).build(),
                )
                runProbe(
                    "ipv4-http1",
                    baseBuilder()
                        .dns(ipv4OnlyDns)
                        .protocols(listOf(Protocol.HTTP_1_1))
                        .build(),
                )

                val tls12 = ConnectionSpec.Builder(ConnectionSpec.MODERN_TLS)
                    .tlsVersions(TlsVersion.TLS_1_2)
                    .build()
                runProbe(
                    "ipv4-tls12",
                    baseBuilder()
                        .dns(ipv4OnlyDns)
                        .connectionSpecs(listOf(tls12))
                        .build(),
                )

                val tls13 = ConnectionSpec.Builder(ConnectionSpec.MODERN_TLS)
                    .tlsVersions(TlsVersion.TLS_1_3)
                    .build()
                runProbe(
                    "ipv4-tls13",
                    baseBuilder()
                        .dns(ipv4OnlyDns)
                        .connectionSpecs(listOf(tls13))
                        .build(),
                )
            } finally {
                Log.e(TLS_PROBE_TAG, "END probe matrix")
                running.set(false)
            }
        }.apply {
            name = "tajik-stt-tls-diag"
            isDaemon = true
            start()
        }
    }

    private fun baseBuilder(): OkHttpClient.Builder = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .writeTimeout(5, TimeUnit.SECONDS)
        .callTimeout(7, TimeUnit.SECONDS)

    private fun runProbe(name: String, client: OkHttpClient) {
        val request = Request.Builder().url(TLS_PROBE_URL).get().build()
        try {
            client.newCall(request).execute().use { response ->
                val handshake = response.handshake
                Log.e(
                    TLS_PROBE_TAG,
                    "PROBE $name SUCCESS code=${response.code} protocol=${response.protocol} " +
                        "tls=${handshake?.tlsVersion} cipher=${handshake?.cipherSuite}",
                )
            }
        } catch (error: Throwable) {
            Log.e(
                TLS_PROBE_TAG,
                "PROBE $name FAIL ${error.javaClass.name}: ${error.message ?: "<no message>"}",
                error,
            )
        }
    }
}
