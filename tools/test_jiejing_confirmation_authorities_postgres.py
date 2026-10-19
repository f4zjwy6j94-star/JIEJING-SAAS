#!/usr/bin/env python3
"""B0 lifecycle suite on one owned loopback PostgreSQL cluster, never an input DSN.

Reuse the already reviewed owned initdb/pg_ctl runner; each case gets a fresh DB.
No real credentials, sellers, provider adapter or production data.
"""
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_jiejing_support_postgres as owned
from test_jiejing_confirmation_authorities import ApprovalLifecycleTests


class ApprovalPostgresTests(ApprovalLifecycleTests):
    def setUp(self):
        database='authority_test_'+uuid.uuid4().hex[:16]
        with owned.psycopg.connect(owned.ADMIN_DSN,autocommit=True) as conn:
            conn.execute(owned.psycopg.sql.SQL('create database {}').format(owned.psycopg.sql.Identifier(database)))
        self.dsn=owned.ADMIN_DSN.rsplit('/',1)[0]+'/'+database
        from jiejing_saas.infrastructure_drivers import run_postgres_migration
        migrated=run_postgres_migration(database_url=self.dsn)
        self.assertEqual(migrated['status'],'ok',migrated)
        from jiejing_saas.repository import SaaSRepository
        self.repo=SaaSRepository(owned.RUN/'unused.sqlite',database_engine='postgres',database_url=self.dsn)
        self.seed_account()

    def tearDown(self):
        from jiejing_saas.postgres_repository_runtime import close_postgres_pools
        close_postgres_pools()


if __name__=='__main__':
    owned.SupportPostgresTests=ApprovalPostgresTests
    raise SystemExit(owned.main())
