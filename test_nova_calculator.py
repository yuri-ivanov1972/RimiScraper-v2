import unittest

from psycopg2.extras import RealDictCursor

from nova_calculator import assign_nova_score


class NovaCursor:
    def __init__(self, connection):
        self.connection = connection
        self.current_row = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.connection.queries.append((normalized, params))
        if self.connection.error:
            raise self.connection.error
        if normalized.startswith("SELECT nova_source"):
            self.current_row = self.connection.product_row
        elif "COUNT(*) AS bad_count" in normalized:
            self.current_row = {"bad_count": self.connection.bad_count}
        elif normalized.startswith("SELECT nc.nova_score"):
            self.current_row = self.connection.category_row
        elif normalized.startswith("UPDATE products"):
            self.connection.update_params = params
            self.current_row = None
        else:
            raise AssertionError(f"Unexpected query: {normalized}")

    def fetchone(self):
        return self.current_row


class NovaConnection:
    def __init__(
        self,
        *,
        nova_source=None,
        bad_count=0,
        category_score=None,
        category_exists=True,
        error=None,
    ):
        self.product_row = {"nova_source": nova_source}
        self.bad_count = bad_count
        self.category_row = (
            {"nova_score": category_score} if category_exists else None
        )
        self.error = error
        self.cursor_factories = []
        self.queries = []
        self.update_params = None
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, cursor_factory=None):
        self.cursor_factories.append(cursor_factory)
        return NovaCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class NovaCalculatorTests(unittest.TestCase):
    def test_manual_override_is_not_touched(self):
        connection = NovaConnection(nova_source="manual_override")

        result = assign_nova_score(connection, 7, "SKU-7")

        self.assertTrue(result["skipped"])
        self.assertEqual(result["nova_source"], "manual_override")
        self.assertIsNone(connection.update_params)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.cursor_factories, [RealDictCursor])

    def test_avoid_or_limit_ingredient_assigns_additive_override(self):
        connection = NovaConnection(bad_count=2, category_score=1)

        result = assign_nova_score(connection, 7, "SKU-7")

        self.assertEqual(
            result,
            {
                "nova_score": 4,
                "nova_source": "additive_override",
                "skipped": False,
                "reason": "ok",
            },
        )
        self.assertEqual(
            connection.update_params,
            (4, "additive_override", 7),
        )
        self.assertEqual(connection.commits, 1)

    def test_category_score_is_inherited_for_products_without_bad_additives(self):
        connection = NovaConnection(bad_count=0, category_score=2)

        result = assign_nova_score(connection, 7, "SKU-7")

        self.assertEqual(result["nova_score"], 2)
        self.assertEqual(result["nova_source"], "category_inherited")
        self.assertEqual(
            connection.update_params,
            (2, "category_inherited", 7),
        )
        self.assertEqual(connection.commits, 1)

    def test_missing_category_score_records_null_inheritance(self):
        connection = NovaConnection(bad_count=0, category_score=None)

        result = assign_nova_score(connection, 7, "SKU-7")

        self.assertIsNone(result["nova_score"])
        self.assertEqual(result["nova_source"], "category_inherited")
        self.assertEqual(
            connection.update_params,
            (None, "category_inherited", 7),
        )
        self.assertEqual(connection.commits, 1)

    def test_database_failure_rolls_back_and_reports_exception_type(self):
        connection = NovaConnection(error=RuntimeError("database unavailable"))

        with self.assertLogs("nova_calculator", level="WARNING") as logs:
            result = assign_nova_score(connection, 7, "SKU-7")

        self.assertTrue(result["skipped"])
        self.assertEqual(
            result["reason"],
            "RuntimeError: database unavailable",
        )
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.commits, 0)
        self.assertIn(
            "RuntimeError: database unavailable",
            "\n".join(logs.output),
        )


if __name__ == "__main__":
    unittest.main()