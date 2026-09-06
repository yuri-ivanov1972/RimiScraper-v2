import unittest
import inspect
import os
import re
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psycopg2
from psycopg2.extras import RealDictCursor

from enhanced_update_coordinator import EnhancedUpdateCoordinator
from suspicious_refresh import (
    LEGACY_PRODUCT_STATUSES,
    is_active_refresh_job,
    queue_suspicious_refresh,
    validate_product,
)
from worker import ProcessingWorker


class QueueCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if "pg_advisory_xact_lock" in normalized:
            self.rows = [{"pg_advisory_xact_lock": None}]
        elif (
            "FROM category_processing_jobs" in normalized
            and "status IN ('queued', 'in_progress')" in normalized
        ):
            self.rows = (
                [{"id": self.connection.active_job_id}]
                if self.connection.active_job_id
                else []
            )
        elif "FROM nutrition_validation nv" in normalized:
            self.rows = list(self.connection.suspicious_products)
        elif normalized.startswith("INSERT INTO category_processing_jobs"):
            self.rows = [{"id": 42}]
        elif normalized.startswith("INSERT INTO job_events"):
            self.connection.event_written = True
            self.rows = []
        else:
            raise AssertionError(f"Unexpected query: {normalized}")

    def executemany(self, query, params):
        self.connection.product_rows.extend(params)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class QueueConnection:
    def __init__(self, active_job_id=None):
        self.active_job_id = active_job_id
        self.suspicious_products = [
            {"product_id": 7, "sku": "SKU-7"},
            {"product_id": 9, "sku": "SKU-9"},
        ]
        self.product_rows = []
        self.event_written = False
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return QueueCursor(self)

    def commit(self):
        self.commits += 1


class ValidationCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if "FROM products p LEFT JOIN nutritionfacts" in normalized:
            self.rows = [dict(self.connection.product)]
        elif "FROM ingredient_product_mapping" in normalized:
            self.rows = [{"ingredient": "cukurs", "clean_name": None}]
        elif normalized.startswith("INSERT INTO nutrition_validation"):
            self.connection.upsert_params = params
            self.rows = []
        else:
            raise AssertionError(f"Unexpected query: {normalized}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class ValidationConnection:
    def __init__(self):
        self.product = {
            "product_id": 7,
            "sku": "SKU-7",
            "ingredients_text": "cukurs",
            "energy_kcal": 100,
            "energy_kj": 418,
            "fat_total": 0,
            "fat_saturated": 0,
            "carbs_total": 20,
            "carbs_sugars": 0,
            "protein": 0,
            "salt": 0,
            "fiber": 0,
        }
        self.upsert_params = None
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return ValidationCursor(self)

    def commit(self):
        self.commits += 1


class NoCloseConnection:
    """Delegate a test connection while letting the test inspect it afterward."""

    def __init__(self, connection):
        self.connection = connection

    def cursor(self, *args, **kwargs):
        return self.connection.cursor(*args, **kwargs)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        pass


class FakeWebClient:
    def get_product_data(self, sku):
        return {
            "soup": object(),
            "url": f"https://example.test/{sku}",
            "name": "Test product 100 g",
            "price": "1.00",
            "is_available": True,
            "photos": [],
        }

    def extract_nutrition_data(self, soup, url):
        return {
            "category_code": "SH-1",
            "category_path_full": "Test",
            "has_nutrition": True,
            "ingredients": "cukurs",
            "carbs_sugars": 10,
        }


class FakeDatabaseUpdater:
    def __init__(self):
        self.force_overwrite = None
        self.preserve_manual_nutrition = None

    def get_product_by_sku(self, sku):
        return {"product_id": 7, "sku": sku, "category_id": 2}

    def force_update_product_data(
        self,
        sku,
        product_data,
        force_overwrite=True,
        is_new_product=False,
        preserve_manual_nutrition=False,
    ):
        self.force_overwrite = force_overwrite
        self.preserve_manual_nutrition = preserve_manual_nutrition
        return True


class SuspiciousRefreshTests(unittest.TestCase):
    def test_empty_refresh_history_is_not_active(self):
        self.assertIs(is_active_refresh_job(None), False)

    def test_queued_and_running_refreshes_are_active(self):
        self.assertIs(is_active_refresh_job({"status": "queued"}), True)
        self.assertIs(is_active_refresh_job({"status": "in_progress"}), True)

    def test_completed_refresh_is_not_active(self):
        self.assertIs(is_active_refresh_job({"status": "completed"}), False)

    def test_refresh_uses_only_production_compatible_shared_statuses(self):
        self.assertEqual(
            LEGACY_PRODUCT_STATUSES,
            {"pending", "processing", "completed", "failed", "skipped"},
        )

    def test_worker_refresh_sql_uses_only_legacy_shared_statuses(self):
        source = inspect.getsource(
            ProcessingWorker._process_suspicious_refresh_job
        )
        assigned_statuses = set(
            re.findall(r"SET status = '([a-z_]+)'", source)
        )
        self.assertTrue(assigned_statuses)
        self.assertLessEqual(assigned_statuses, LEGACY_PRODUCT_STATUSES)
        self.assertIn("scrape_status = 'processing'", source)
        self.assertIn("validation_status = 'processing'", source)

    @unittest.skipUnless(
        os.environ.get("DATABASE_URL"),
        "Development database is unavailable",
    )
    def test_worker_statuses_satisfy_production_constraint(self):
        connection = psycopg2.connect(os.environ["DATABASE_URL"])
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TEMP TABLE refresh_status_compatibility (
                        id SERIAL PRIMARY KEY,
                        status VARCHAR(20) CHECK (
                            status IN (
                                'pending', 'processing', 'completed',
                                'failed', 'skipped'
                            )
                        ),
                        scrape_status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        validation_status VARCHAR(20) NOT NULL DEFAULT 'pending'
                    )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO refresh_status_compatibility (status)
                    VALUES ('pending')
                    RETURNING id
                    """
                )
                row_id = cursor.fetchone()[0]

                # Full successful lifecycle under the production constraint.
                cursor.execute(
                    """
                    UPDATE refresh_status_compatibility
                    SET status = 'processing', scrape_status = 'processing'
                    WHERE id = %s
                    """,
                    (row_id,),
                )
                cursor.execute(
                    """
                    UPDATE refresh_status_compatibility
                    SET status = 'processing', scrape_status = 'completed',
                        validation_status = 'pending'
                    WHERE id = %s
                    """,
                    (row_id,),
                )
                cursor.execute(
                    """
                    UPDATE refresh_status_compatibility
                    SET status = 'processing', validation_status = 'processing'
                    WHERE id = %s
                    """,
                    (row_id,),
                )
                cursor.execute(
                    """
                    UPDATE refresh_status_compatibility
                    SET status = 'completed', validation_status = 'completed'
                    WHERE id = %s
                    """,
                    (row_id,),
                )

                # Interrupted scrape and validation resume independently.
                cursor.execute(
                    """
                    INSERT INTO refresh_status_compatibility (
                        status, scrape_status, validation_status
                    )
                    VALUES
                        ('processing', 'processing', 'pending'),
                        ('processing', 'completed', 'processing')
                    """
                )
                cursor.execute(
                    """
                    UPDATE refresh_status_compatibility
                    SET status = 'pending', scrape_status = 'pending',
                        validation_status = 'pending'
                    WHERE scrape_status = 'processing'
                    """
                )
                cursor.execute(
                    """
                    UPDATE refresh_status_compatibility
                    SET status = 'processing', validation_status = 'pending'
                    WHERE scrape_status = 'completed'
                      AND validation_status = 'processing'
                    """
                )
                cursor.execute(
                    """
                    SELECT status, scrape_status, validation_status
                    FROM refresh_status_compatibility
                    ORDER BY id
                    """
                )
                self.assertEqual(
                    cursor.fetchall(),
                    [
                        ("completed", "completed", "completed"),
                        ("pending", "pending", "pending"),
                        ("processing", "completed", "pending"),
                    ],
                )
        finally:
            connection.rollback()
            connection.close()

    @unittest.skipUnless(
        os.environ.get("DATABASE_URL"),
        "Development database is unavailable",
    )
    def test_full_worker_refresh_with_production_constraint(self):
        connection = psycopg2.connect(
            os.environ["DATABASE_URL"],
            cursor_factory=RealDictCursor,
        )
        wrapped_connection = NoCloseConnection(connection)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TEMP TABLE category_processing_jobs (
                        id INTEGER PRIMARY KEY,
                        status VARCHAR(20) NOT NULL,
                        phase VARCHAR(20) NOT NULL,
                        total_products INTEGER NOT NULL,
                        processed_count INTEGER NOT NULL DEFAULT 0,
                        validation_completed_count INTEGER NOT NULL DEFAULT 0,
                        validation_failed_count INTEGER NOT NULL DEFAULT 0,
                        current_worker_id VARCHAR(100),
                        last_updated TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TEMP TABLE product_processing_log (
                        id INTEGER PRIMARY KEY,
                        job_id INTEGER NOT NULL,
                        sku VARCHAR(50) NOT NULL,
                        product_id INTEGER,
                        status VARCHAR(20) NOT NULL CHECK (
                            status IN (
                                'pending', 'processing', 'completed',
                                'failed', 'skipped'
                            )
                        ),
                        scrape_status VARCHAR(20) NOT NULL,
                        validation_status VARCHAR(20) NOT NULL,
                        error_message TEXT,
                        processed_at TIMESTAMP
                    )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO category_processing_jobs (
                        id, status, phase, total_products, current_worker_id
                    )
                    VALUES (42, 'in_progress', 'queued', 1, 'test-worker')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO product_processing_log (
                        id, job_id, sku, product_id, status,
                        scrape_status, validation_status
                    )
                    VALUES (
                        1, 42, 'SKU-7', 7, 'pending', 'pending', 'pending'
                    )
                    """
                )
            connection.commit()

            class FakeCoordinator:
                def __init__(self, status_callback):
                    pass

                def process_single_product_with_auto_category(self, *args, **kwargs):
                    return SimpleNamespace(
                        success=True,
                        changes={},
                        errors=[],
                    )

                def close(self):
                    pass

            worker = ProcessingWorker.__new__(ProcessingWorker)
            worker.worker_id = "test-worker"
            worker.current_job_id = None
            worker.logger = Mock()
            worker._get_db_connection = lambda: wrapped_connection
            worker.update_heartbeat = lambda *args, **kwargs: None
            worker.log_event = lambda *args, **kwargs: None

            with (
                patch(
                    "enhanced_update_coordinator.EnhancedUpdateCoordinator",
                    FakeCoordinator,
                ),
                patch("suspicious_refresh.validate_product", lambda *args: {}),
            ):
                worker._process_suspicious_refresh_job(
                    {"id": 42, "total_products": 1}
                )

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, phase, processed_count,
                           validation_completed_count
                    FROM category_processing_jobs
                    WHERE id = 42
                    """
                )
                self.assertEqual(
                    dict(cursor.fetchone()),
                    {
                        "status": "completed",
                        "phase": "completed",
                        "processed_count": 1,
                        "validation_completed_count": 1,
                    },
                )
                cursor.execute(
                    """
                    SELECT status, scrape_status, validation_status
                    FROM product_processing_log
                    WHERE id = 1
                    """
                )
                self.assertEqual(
                    dict(cursor.fetchone()),
                    {
                        "status": "completed",
                        "scrape_status": "completed",
                        "validation_status": "completed",
                    },
                )
        finally:
            connection.rollback()
            connection.close()

    def test_queue_snapshots_all_suspicious_products(self):
        connection = QueueConnection()
        job_id, count = queue_suspicious_refresh(connection)

        self.assertEqual((job_id, count), (42, 2))
        self.assertEqual(
            connection.product_rows,
            [(42, "SKU-7", 7), (42, "SKU-9", 9)],
        )
        self.assertTrue(connection.event_written)
        self.assertEqual(connection.commits, 1)

    def test_queue_rejects_duplicate_active_refresh(self):
        with self.assertRaisesRegex(ValueError, "already active"):
            queue_suspicious_refresh(QueueConnection(active_job_id=41))

    def test_validation_replaces_report_only_after_success(self):
        connection = ValidationConnection()
        result = validate_product(connection, 7)

        self.assertEqual(result["suspicion_level"], "medium")
        self.assertEqual(connection.upsert_params[0], 7)
        self.assertEqual(connection.commits, 1)

    def test_validation_failure_does_not_replace_previous_report(self):
        class FailingValidator:
            def validate(self, ingredients, product):
                raise ValueError("bad validation input")

        connection = ValidationConnection()
        with self.assertRaisesRegex(ValueError, "bad validation input"):
            validate_product(connection, 7, validator=FailingValidator())

        self.assertIsNone(connection.upsert_params)
        self.assertEqual(connection.commits, 0)

    def test_checks_refresh_preserves_manual_nutrition(self):
        coordinator = EnhancedUpdateCoordinator.__new__(EnhancedUpdateCoordinator)
        coordinator.status_callback = lambda message: None
        coordinator.web_client = FakeWebClient()
        coordinator.db_updater = FakeDatabaseUpdater()
        coordinator._get_category_id = lambda code: 2
        coordinator._check_data_corruption = lambda product: False
        coordinator._parse_quantity = lambda name: (100, "g")

        result = coordinator.process_single_product_with_auto_category(
            "SKU-7",
            force_update=True,
            preserve_manual_nutrition=True,
        )

        self.assertTrue(result.success)
        self.assertTrue(coordinator.db_updater.force_overwrite)
        self.assertTrue(coordinator.db_updater.preserve_manual_nutrition)

    def test_worker_dispatches_dedicated_refresh_job(self):
        worker = ProcessingWorker.__new__(ProcessingWorker)
        received = []
        worker._process_suspicious_refresh_job = received.append

        worker.process_job({"id": 42, "job_type": "suspicious_refresh"})

        self.assertEqual(
            received,
            [{"id": 42, "job_type": "suspicious_refresh"}],
        )


if __name__ == "__main__":
    unittest.main()