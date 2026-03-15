from app.services.layout_service import _subnet_key, compute_subnet_layout


class TestSubnetKey:
    def test_ipv4_extracts_24_slice(self):
        assert _subnet_key("192.168.1.42") == "192.168.1"

    def test_different_subnets(self):
        assert _subnet_key("10.0.0.1") == "10.0.0"
        assert _subnet_key("10.0.1.1") == "10.0.1"

    def test_no_ip_returns_none(self):
        assert _subnet_key(None) is None

    def test_malformed_ip_returns_none(self):
        assert _subnet_key("not-an-ip") is None


class TestComputeSubnetLayout:
    def _hw(self, id, ip, role="server"):
        return {"id": id, "ip_address": ip, "role": role}

    def test_single_subnet_places_all_nodes(self):
        hw = [
            self._hw(1, "192.168.1.1", "router"),
            self._hw(2, "192.168.1.10"),
            self._hw(3, "192.168.1.11"),
        ]
        pos = compute_subnet_layout(hw)
        assert len(pos) == 3
        for i in [1, 2, 3]:
            assert "x" in pos[i] and "y" in pos[i]

    def test_router_placed_above_others(self):
        hw = [
            self._hw(1, "192.168.1.1", "router"),
            self._hw(2, "192.168.1.10"),
            self._hw(3, "192.168.1.20"),
        ]
        pos = compute_subnet_layout(hw)
        assert pos[1]["y"] < pos[2]["y"]

    def test_two_subnets_separated_horizontally(self):
        hw = [self._hw(1, "192.168.1.1"), self._hw(2, "192.168.2.1")]
        pos = compute_subnet_layout(hw)
        assert pos[1]["x"] != pos[2]["x"]

    def test_no_ip_placed_in_overflow(self):
        hw = [self._hw(1, None), self._hw(2, "192.168.1.1")]
        pos = compute_subnet_layout(hw)
        assert 1 in pos and 2 in pos

    def test_empty_returns_empty(self):
        assert compute_subnet_layout([]) == {}
