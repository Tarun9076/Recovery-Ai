from sqlalchemy import text


def test_database_connection(test_engine):
    with test_engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar_one()
    assert result == 1


def test_expected_tables_exist(test_engine):
    with test_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        ).all()
    table_names = {r[0] for r in rows}
    expected = {"merchants", "customers", "orders", "payments", "payment_failures", "merchant_policies"}
    assert expected.issubset(table_names)
