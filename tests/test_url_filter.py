import pytest

from pillywiggins.skills.url_filter import is_safe_url


class TestIsSafeUrl:
    def test_public_domain(self):
        assert is_safe_url("https://example.com") is True

    def test_public_ip(self):
        assert is_safe_url("http://93.184.216.34/") is True

    def test_loopback_ipv4(self):
        assert is_safe_url("http://127.0.0.1/") is False

    def test_loopback_127_any(self):
        assert is_safe_url("http://127.0.0.99:8080/") is False

    def test_10_network(self):
        assert is_safe_url("http://10.0.0.1/") is False

    def test_172_16_network(self):
        assert is_safe_url("http://172.16.0.1/") is False

    def test_172_31_network(self):
        assert is_safe_url("http://172.31.255.255/") is False

    def test_172_32_is_public(self):
        assert is_safe_url("http://172.32.0.1/") is True

    def test_192_168_network(self):
        assert is_safe_url("http://192.168.1.1/") is False

    def test_169_254_link_local(self):
        assert is_safe_url("http://169.254.1.1/") is False

    def test_0_0_0_0(self):
        assert is_safe_url("http://0.0.0.0/") is False

    def test_ipv6_loopback(self):
        assert is_safe_url("http://[::1]/") is False

    def test_ipv6_ula(self):
        assert is_safe_url("http://[fd00::1]/") is False

    def test_public_ipv6(self):
        assert is_safe_url("http://[2001:db8::1]/") is True

    def test_empty_string(self):
        assert is_safe_url("") is False

    def test_no_host(self):
        assert is_safe_url("http:///path") is False

    def test_domain_not_ip(self):
        assert is_safe_url("https://www.google.com/search?q=test") is True

    def test_port_preserved(self):
        assert is_safe_url("http://192.168.1.1:8080/") is False

    def test_public_with_port(self):
        assert is_safe_url("http://93.184.216.34:443/") is True