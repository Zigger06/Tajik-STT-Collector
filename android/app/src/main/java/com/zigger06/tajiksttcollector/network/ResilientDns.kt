package com.zigger06.tajiksttcollector.network

import okhttp3.Dns
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.dnsoverhttps.DnsOverHttps
import java.net.Inet4Address
import java.net.InetAddress
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit

/**
 * Prefer Android's system/operator DNS because it is the path the rest of the
 * device uses and it can already resolve the public Funnel host on most phones.
 * DNS-over-HTTPS is kept only as a recovery path for operators/private-DNS
 * configurations where the system resolver genuinely fails.
 *
 * The fallback must also run when a resolver returns an empty list without
 * throwing. Some DoH/network combinations behave exactly that way.
 */
internal class FallbackDns(
    private val primary: Dns,
    private val fallback: Dns,
) : Dns {
    override fun lookup(hostname: String): List<InetAddress> {
        var primaryError: Throwable? = null
        val primaryAddresses = try {
            primary.lookup(hostname)
        } catch (error: Throwable) {
            primaryError = error
            emptyList()
        }
        if (primaryAddresses.isNotEmpty()) return normalize(primaryAddresses)

        var fallbackError: Throwable? = null
        val fallbackAddresses = try {
            fallback.lookup(hostname)
        } catch (error: Throwable) {
            fallbackError = error
            emptyList()
        }
        if (fallbackAddresses.isNotEmpty()) return normalize(fallbackAddresses)

        val failure = UnknownHostException("Could not resolve host: $hostname")
        when {
            fallbackError != null -> failure.initCause(fallbackError)
            primaryError != null -> failure.initCause(primaryError)
        }
        if (primaryError != null && primaryError !== failure.cause) {
            failure.addSuppressed(primaryError)
        }
        if (fallbackError != null && fallbackError !== failure.cause) {
            failure.addSuppressed(fallbackError)
        }
        throw failure
    }

    private fun normalize(addresses: List<InetAddress>): List<InetAddress> =
        addresses.distinct().sortedBy { address ->
            if (address is Inet4Address) 0 else 1
        }
}

object ResilientDns : Dns {
    private val bootstrapClient = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(6, TimeUnit.SECONDS)
        .callTimeout(8, TimeUnit.SECONDS)
        .build()

    private val secureDns: Dns = DnsOverHttps.Builder()
        .client(bootstrapClient)
        .url("https://dns.google/dns-query".toHttpUrl())
        .bootstrapDnsHosts(
            InetAddress.getByName("8.8.8.8"),
            InetAddress.getByName("8.8.4.4"),
        )
        .includeIPv6(true)
        .build()

    private val delegate = FallbackDns(
        primary = Dns.SYSTEM,
        fallback = secureDns,
    )

    override fun lookup(hostname: String): List<InetAddress> = delegate.lookup(hostname)
}
