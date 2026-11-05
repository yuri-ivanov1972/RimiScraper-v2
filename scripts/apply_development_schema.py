"""Apply the product percentage column during development-only post-merge setup."""

import os
from contextlib import closing

import psycopg2


def apply_development_schema(environ=None):
    env = os.environ if environ is None else environ
    if (
        env.get("DEV_MODE", "").lower() not in ("true", "1", "yes")
        and env.get("ENVIRONMENT", "").lower() not in ("dev", "development")
    ):
        raise RuntimeError("Development schema setup requires development mode")
    url = env.get("DATABASE_URL")
    if not url or url == env.get("PROD_DATABASE_URL"):
        raise RuntimeError("Development schema setup requires a distinct development database")
    with closing(psycopg2.connect(url, connect_timeout=10)) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    ALTER TABLE nutritionfacts
                    ADD COLUMN IF NOT EXISTS fruit_veg_legume_percent NUMERIC(5,2)
                    CHECK (fruit_veg_legume_percent BETWEEN 0 AND 100)
                """)


if __name__ == "__main__":
    apply_development_schema()
