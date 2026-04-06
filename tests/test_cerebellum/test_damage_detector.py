from terraria_agent.cerebellum.damage_detector import DamageDetector


class TestDamageDetection:
    def test_no_damage_first_update(self):
        d = DamageDetector()
        info = d.update(100, 100, 0.0)
        assert not info.took_damage
        assert info.damage_amount == 0

    def test_damage_detected(self):
        d = DamageDetector()
        d.update(100, 100, 0.0)
        info = d.update(80, 100, 0.2)
        assert info.took_damage
        assert info.damage_amount == 20

    def test_no_damage_on_stable_hp(self):
        d = DamageDetector()
        d.update(100, 100, 0.0)
        info = d.update(100, 100, 0.2)
        assert not info.took_damage

    def test_healing_not_damage(self):
        d = DamageDetector()
        d.update(50, 100, 0.0)
        info = d.update(80, 100, 0.2)
        assert not info.took_damage
        assert info.damage_amount == 0


class TestDangerLevel:
    def test_safe_full_hp(self):
        d = DamageDetector()
        info = d.update(100, 100, 10.0)
        assert info.danger_level == "safe"

    def test_critical_low_hp(self):
        d = DamageDetector()
        info = d.update(20, 100, 10.0)
        assert info.danger_level == "critical"

    def test_warning_mid_hp(self):
        d = DamageDetector()
        info = d.update(50, 100, 10.0)
        assert info.danger_level == "warning"

    def test_warning_recent_damage(self):
        d = DamageDetector()
        d.update(100, 100, 0.0)
        d.update(80, 100, 1.0)
        info = d.update(80, 100, 2.5)
        assert info.danger_level == "warning"

    def test_safe_after_time_passes(self):
        d = DamageDetector()
        d.update(100, 100, 0.0)
        d.update(80, 100, 0.2)
        info = d.update(80, 100, 10.0)
        assert info.danger_level == "safe"


class TestHpTrend:
    def test_stable_initially(self):
        d = DamageDetector()
        info = d.update(100, 100, 0.0)
        assert info.hp_trend == "stable"

    def test_decreasing(self):
        d = DamageDetector()
        d.update(100, 100, 0.0)
        d.update(90, 100, 0.2)
        info = d.update(80, 100, 0.4)
        assert info.hp_trend == "decreasing"

    def test_recovering(self):
        d = DamageDetector()
        d.update(50, 100, 0.0)
        d.update(60, 100, 0.2)
        info = d.update(70, 100, 0.4)
        assert info.hp_trend == "recovering"

    def test_stable_same_hp(self):
        d = DamageDetector()
        d.update(80, 100, 0.0)
        d.update(80, 100, 0.2)
        info = d.update(80, 100, 0.4)
        assert info.hp_trend == "stable"


class TestReset:
    def test_reset_clears_state(self):
        d = DamageDetector()
        d.update(100, 100, 0.0)
        d.update(50, 100, 0.2)
        d.reset()
        info = d.update(50, 100, 10.0)
        assert not info.took_damage
        assert info.hp_trend == "stable"
