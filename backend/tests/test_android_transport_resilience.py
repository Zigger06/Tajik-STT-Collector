from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class AndroidTransportResilienceTest(unittest.TestCase):
    def test_funnel_transport_prefers_ipv4_and_has_total_timeout(self) -> None:
        api = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ApiClient.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("private object Ipv4FirstDns : Dns", api)
        self.assertIn("Dns.SYSTEM.lookup(hostname).sortedBy", api)
        self.assertIn("address is Inet4Address", api)
        self.assertIn(".dns(Ipv4FirstDns)", api)
        self.assertIn(".connectTimeout(5, TimeUnit.SECONDS)", api)
        self.assertIn(".callTimeout(20, TimeUnit.SECONDS)", api)

    def test_setup_does_not_waste_a_separate_health_round_trip(self) -> None:
        api = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ApiClient.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("suspend fun checkHealth(): Boolean = true", api)
        self.assertIn("execute(registrationRequest(body))", api)
        self.assertIn("registrationChallenge()", api)


if __name__ == "__main__":
    unittest.main()
