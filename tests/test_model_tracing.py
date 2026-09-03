"""Tests for privacy-safe model call traces."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from miniclaudecode.runtime.model_tracing import ModelCallRecorder, build_model_call_event


class TestModelTracing(unittest.TestCase):
    def test_event_records_metrics_and_calculates_configured_cost(self):
        started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        response = SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=2_000_000, cache_read_input_tokens=1_000_000),
        )
        event = build_model_call_event(
            run_id="run", turn=1, model="test-model", response=response,
            started_at=started_at, ended_at=started_at + timedelta(milliseconds=25),
            input_cost_per_million_usd=3.0, output_cost_per_million_usd=15.0,
            cache_read_cost_per_million_usd=0.3,
        )

        self.assertEqual(event["duration_ms"], 25)
        self.assertEqual(event["stop_reason"], "end_turn")
        self.assertEqual(event["estimated_cost_usd"], 33.3)
        self.assertNotIn("prompt", event)
        self.assertNotIn("content", event)

    def test_recorder_writes_dedicated_jsonl_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = ModelCallRecorder(trace_dir=tmpdir)
            now = datetime.now(timezone.utc)
            recorder.record(
                run_id="run", turn=1, model="test", response=SimpleNamespace(usage=None, stop_reason="end_turn"),
                started_at=now, ended_at=now,
            )
            self.assertTrue((__import__("pathlib").Path(tmpdir) / "model_calls.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
