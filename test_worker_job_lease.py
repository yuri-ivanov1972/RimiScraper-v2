import time
import unittest
from unittest.mock import Mock

from worker import ProcessingWorker


class HeartbeatCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 0

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.connection.queries.append((normalized, params))
        self.rowcount = (
            1 if normalized.startswith("UPDATE category_processing_jobs") else 0
        )

    def close(self):
        pass


class HeartbeatConnection:
    def __init__(self):
        self.queries = []
        self.commits = 0
        self.closed = False

    def cursor(self):
        return HeartbeatCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class WorkerJobLeaseTests(unittest.TestCase):
    def test_heartbeat_renews_only_the_owned_job(self):
        connection = HeartbeatConnection()
        worker = ProcessingWorker.__new__(ProcessingWorker)
        worker.worker_id = "worker-a"
        worker.heartbeat_interval = 30
        worker.last_heartbeat_time = 0
        worker.last_heartbeat_status = None
        worker.last_heartbeat_job_id = None
        worker.logger = Mock()
        worker._get_db_connection = lambda: connection

        worker.update_heartbeat("processing", 42, force=True)

        self.assertEqual(connection.commits, 1)
        self.assertTrue(connection.closed)
        job_updates = [
            (query, params)
            for query, params in connection.queries
            if query.startswith("UPDATE category_processing_jobs")
        ]
        self.assertEqual(len(job_updates), 1)
        self.assertIn("current_worker_id = %s", job_updates[0][0])
        self.assertEqual(job_updates[0][1], (42, "worker-a"))

    def test_lease_is_renewed_during_long_blocking_work(self):
        worker = ProcessingWorker.__new__(ProcessingWorker)
        worker.heartbeat_interval = 0.01
        worker.update_heartbeat = Mock()

        with worker._maintain_job_lease(42):
            time.sleep(0.035)

        self.assertGreaterEqual(worker.update_heartbeat.call_count, 3)
        worker.update_heartbeat.assert_any_call(
            "processing",
            42,
            force=True,
        )
        calls_after_exit = worker.update_heartbeat.call_count
        time.sleep(0.02)
        self.assertEqual(worker.update_heartbeat.call_count, calls_after_exit)

    def test_process_job_holds_lease_around_dispatch(self):
        worker = ProcessingWorker.__new__(ProcessingWorker)
        events = []

        class Lease:
            def __enter__(self):
                events.append("lease_started")

            def __exit__(self, exc_type, exc, traceback):
                events.append("lease_stopped")

        worker._maintain_job_lease = lambda job_id: Lease()
        worker._process_suspicious_refresh_job = (
            lambda job: events.append("processed")
        )

        worker.process_job(
            {"id": 42, "job_type": "suspicious_refresh"}
        )

        self.assertEqual(
            events,
            ["lease_started", "processed", "lease_stopped"],
        )


if __name__ == "__main__":
    unittest.main()