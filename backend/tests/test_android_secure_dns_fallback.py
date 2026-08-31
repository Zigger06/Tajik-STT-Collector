from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class AndroidSecureDnsFallbackTest(unittest.TestCase):
    def test_system_dns_is_primary_and_doh_is_recovery_only(self) -> None:
        dns = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ResilientDns.kt"
        ).read_text(encoding="utf-8")
        gradle = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
        api = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ApiClient.kt"
        ).read_text(encoding="utf-8")

        self.assertIn('okhttp-dnsoverhttps:4.12.0', gradle)
        self.assertIn('DnsOverHttps.Builder()', dns)
        self.assertIn('https://dns.google/dns-query', dns)
        self.assertIn('InetAddress.getByName("8.8.8.8")', dns)
        self.assertIn('InetAddress.getByName("8.8.4.4")', dns)
        self.assertIn('nonEmpty(Dns.SYSTEM.lookup(hostname))', dns)
        self.assertIn('nonEmpty(secureDns.lookup(hostname))', dns)
        self.assertLess(
            dns.index('nonEmpty(Dns.SYSTEM.lookup(hostname))'),
            dns.index('nonEmpty(secureDns.lookup(hostname))'),
        )
        self.assertNotIn('preferSecure', dns)
        self.assertIn('.dns(ResilientDns)', api)
        self.assertNotIn('.dns(Ipv4FirstDns)\n', api)


if __name__ == "__main__":
    unittest.main()
