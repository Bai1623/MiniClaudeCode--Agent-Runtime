"""Tests for structured trace summaries."""

from __future__ import annotations

import unittest

from miniclaudecode.runtime import TraceSummary


class TestTraceSummary(unittest.TestCase):
    def test_from_events_summarizes_trace_metrics(self):
        summary = TraceSummary.from_events([
            {
                "turn": 1,
                "tool_name": "grep",
                "status": "error",
                "error_type": "validation_error",
                "duration_ms": 10,
                "compressed": False,
                "retried": False,
            },
            {
                "turn": 2,
                "tool_name": "grep",
                "status": "error",
                "error_type": "validation_error",
                "duration_ms": 20,
                "compressed": True,
                "retried": True,
            },
            {
                "turn": 3,
                "tool_name": "read_file",
                "status": "ok",
                "error_type": None,
                "duration_ms": 30,
                "compressed": False,
                "retried": False,
            },
            {
                "turn": 4,
                "tool_name": "grep",
                "status": "error",
                "error_type": "timeout_error",
                "duration_ms": 40,
                "compressed": True,
                "retried": True,
            },
            {
                "turn": 5,
                "tool_name": "bash",
                "status": "ok",
                "error_type": None,
                "duration_ms": 100,
                "compressed": False,
                "retried": False,
            },
        ])

        self.assertEqual(summary.tool_calls, 5)
        self.assertEqual(summary.error_counts, {
            "timeout_error": 1,
            "validation_error": 2,
        })
        self.assertEqual(summary.retry_count, 2)
        self.assertEqual(summary.compressed_calls, 2)
        self.assertEqual(summary.compression_rate, 0.4)
        self.assertEqual(summary.p50_duration_ms, 30)
        self.assertEqual(summary.p95_duration_ms, 100)
        self.assertEqual(
            [(item.tool_name, item.turn, item.duration_ms) for item in summary.slow_tools],
            [("bash", 5, 100), ("grep", 4, 40), ("read_file", 3, 30)],
        )

    def test_from_events_returns_zero_summary_for_empty_input(self):
        summary = TraceSummary.from_events([])

        self.assertEqual(summary.tool_calls, 0)
        self.assertEqual(summary.error_counts, {})
        self.assertEqual(summary.retry_count, 0)
        self.assertEqual(summary.compressed_calls, 0)
        self.assertEqual(summary.compression_rate, 0.0)
        self.assertEqual(summary.p50_duration_ms, 0)
        self.assertEqual(summary.p95_duration_ms, 0)
        self.assertEqual(summary.slow_tools, ())

    def test_summary_containers_are_immutable(self):
        summary = TraceSummary.from_events([{
            "turn": 1,
            "tool_name": "grep",
            "status": "error",
            "error_type": "timeout_error",
            "duration_ms": 10,
            "compressed": False,
            "retried": False,
        }])

        with self.assertRaises(TypeError):
            summary.error_counts["timeout_error"] = 2
        with self.assertRaises(AttributeError):
            summary.slow_tools.append(summary.slow_tools[0])

    def test_nearest_rank_percentile_boundaries(self):
        cases = [
            ([7], 7, 7),
            ([10, 20], 10, 20),
            (list(range(1, 21)), 10, 19),
        ]
        for durations, expected_p50, expected_p95 in cases:
            with self.subTest(durations=durations):
                events = [
                    {
                        "turn": turn,
                        "tool_name": "grep",
                        "status": "ok",
                        "error_type": None,
                        "duration_ms": duration,
                        "compressed": False,
                        "retried": False,
                    }
                    for turn, duration in enumerate(durations, start=1)
                ]

                summary = TraceSummary.from_events(events)

                self.assertEqual(summary.p50_duration_ms, expected_p50)
                self.assertEqual(summary.p95_duration_ms, expected_p95)


if __name__ == "__main__":
    unittest.main()
