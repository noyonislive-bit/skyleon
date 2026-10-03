from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from .progress import apply_heartbeat, merge_ranges, normalize_ranges, subtract

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class RangeMathTests(SimpleTestCase):
    def test_merge_overlapping(self):
        self.assertEqual(merge_ranges([(0, 5), (4, 10), (20, 30)]), [(0, 10), (20, 30)])

    def test_normalize_clamps_and_drops_junk(self):
        self.assertEqual(normalize_ranges([[-5, 3], ["x", 2], [50, 999], [7, 7.1]], 60), [(0, 3), (50, 60)])

    def test_subtract(self):
        self.assertEqual(subtract([(0, 10)], [(2, 4), (6, 8)]), [(0, 2), (4, 6), (8, 10)])


class HeartbeatTests(SimpleTestCase):
    def test_normal_viewing_completes(self):
        ranges, last = [], None
        t = NOW
        for i in range(10):  # 10 heartbeats, 10s each, 100s video
            t = t + timedelta(seconds=10)
            r = apply_heartbeat(stored_ranges=ranges, duration=100, reported_ranges=[[0, (i + 1) * 10]],
                                position=(i + 1) * 10, last_heartbeat_at=last, now=t, threshold_percent=90)
            ranges, last = r.ranges, t
        self.assertTrue(r.completed)
        self.assertEqual(r.percent, 100)

    def test_single_forged_request_cannot_complete(self):
        r = apply_heartbeat(stored_ranges=[], duration=600, reported_ranges=[[0, 600]], position=600,
                            last_heartbeat_at=None, now=NOW, threshold_percent=90)
        self.assertFalse(r.completed)
        self.assertLessEqual(r.watched_seconds, 30)

    def test_rewatching_does_not_double_count(self):
        r = apply_heartbeat(stored_ranges=[[0, 50]], duration=100, reported_ranges=[[0, 50]], position=50,
                            last_heartbeat_at=NOW, now=NOW + timedelta(seconds=60), threshold_percent=90)
        self.assertEqual(r.watched_seconds, 50)
        self.assertEqual(r.accepted_seconds, 0)


class RapidFireTests(SimpleTestCase):
    def test_many_quick_heartbeats_cannot_accumulate(self):
        """Firing heartbeats in a tight loop must not add coverage faster than real playback."""
        ranges, last, first = [], None, NOW
        t = NOW
        for i in range(200):
            t = t + timedelta(milliseconds=50)
            r = apply_heartbeat(stored_ranges=ranges, duration=600, reported_ranges=[[0, 600]], position=600,
                                last_heartbeat_at=last, now=t, threshold_percent=90, first_viewed_at=first)
            ranges, last = r.ranges, t
        elapsed = (t - first).total_seconds()  # 10 s of wall clock
        self.assertLessEqual(r.watched_seconds, (elapsed + 15) * 2 + 0.01)
        self.assertFalse(r.completed)
