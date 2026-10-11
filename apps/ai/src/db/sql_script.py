"""Split a SQL script into single statements.

asyncpg rejects more than one command in a prepared statement, which is how
Alembic's op.execute sends SQL.
"""


def split_sql(script: str) -> list[str]:
    return [part.strip() for part in script.split(";") if part.strip()]
