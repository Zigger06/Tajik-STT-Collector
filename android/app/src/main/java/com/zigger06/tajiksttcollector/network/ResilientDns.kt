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
 * Prefer Android's normal resolver because it is the fastest and most compatible
 * path on healthy devices and networks. Keep bootstrapped DNS-over-HTTPS only as
 * a recovery path for devices/operators where the system resolver cannot resolve
 * the public Funnel hostname.
 *
 * The DoH endpoint is bootstrapped with literal Google Public DNS IPs, so the
 * fallback itself does not depend on Android DNS. API traffic never goes through
 * the resolver; only the hostname lookup does.
 */
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

    override fun lookup(hostname: String): List<InetAddress> {
        val addresses = runCatching {
            nonEmpty(Dns.SYSTEM.lookup(hostname))
        }.getOrElse { systemError ->
            runCatching {
                nonEmpty(secureDns.lookup(hostname))
            }.getOrElse { secureError ->
                val failure = UnknownHostException("Could not resolve host")
                failure.initCause(secureError)
                failure.addSuppressed(systemError)
                throw failure
            }
        }

        return addresses.distinct().sortedBy { address ->
            if (address is Inet4Address) 0 else 1
        }
    }

    private fun nonEmpty(addresses: List<InetAddress>): List<InetAddress> {
        if (addresses.isEmpty()) throw UnknownHostException("Could not resolve host")
        return addresses
    }
}
