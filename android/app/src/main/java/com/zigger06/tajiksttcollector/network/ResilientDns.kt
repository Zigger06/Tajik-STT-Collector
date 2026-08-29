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
 * Android apps normally use the device/operator DNS through Dns.SYSTEM. In the
 * real-phone acceptance test Chrome could open the public *.ts.net Funnel while
 * OkHttp repeatedly failed before the request ever reached the Python server.
 * Chrome can use Secure DNS independently of Android's system resolver, so a bad
 * operator/private-DNS path can affect the app but not Chrome.
 *
 * For the Tailscale Funnel hostname we therefore resolve through DNS-over-HTTPS
 * first. The DoH endpoint itself is bootstrapped with literal Google Public DNS
 * IPs, so this path does not depend on the broken system DNS. Other hosts keep the
 * normal system resolver first and use DoH only as a recovery path.
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
        val preferSecure = hostname.endsWith(".ts.net", ignoreCase = true)
        val first = if (preferSecure) secureDns else Dns.SYSTEM
        val second = if (preferSecure) Dns.SYSTEM else secureDns

        val addresses = runCatching { first.lookup(hostname) }
            .getOrElse { firstError ->
                runCatching { second.lookup(hostname) }
                    .getOrElse { secondError ->
                        val failure = UnknownHostException("Could not resolve host")
                        failure.initCause(secondError)
                        failure.addSuppressed(firstError)
                        throw failure
                    }
            }

        if (addresses.isEmpty()) throw UnknownHostException("Could not resolve host")
        return addresses.distinct().sortedBy { address ->
            if (address is Inet4Address) 0 else 1
        }
    }
}
