import os
import sys
from pathlib import Path

import pymysql
from alembic import command
from alembic.config import Config


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app import models  # noqa: F401,E402


def main() -> None:
    root_password = os.environ.get("MYSQL_ROOT_PASSWORD")
    if not root_password:
        raise SystemExit("MYSQL_ROOT_PASSWORD is required")
    connection = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user="root",
        password=root_password,
        charset="utf8mb4",
        autocommit=True,
    )
    database = settings.mysql_database.replace("`", "")
    user = settings.mysql_user.replace("'", "")
    password = settings.mysql_password.replace("'", "''")
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        cursor.execute(f"CREATE USER IF NOT EXISTS '{user}'@'localhost' IDENTIFIED BY '{password}'")
        cursor.execute(f"ALTER USER '{user}'@'localhost' IDENTIFIED BY '{password}'")
        cursor.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX "
            f"ON `{database}`.* TO '{user}'@'localhost'"
        )
        cursor.execute("FLUSH PRIVILEGES")
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(alembic, "head")
    with connection.cursor() as cursor:
        cursor.execute(f"REVOKE CREATE, ALTER, INDEX ON `{database}`.* FROM '{user}'@'localhost'")
        cursor.execute("FLUSH PRIVILEGES")
        cursor.execute(f"SHOW GRANTS FOR '{user}'@'localhost'")
        runtime_grants = [row[0] for row in cursor.fetchall()]
    connection.close()
    print(f"initialized database={database} tables={len(Base.metadata.tables)}")
    print("runtime grants:", *runtime_grants, sep="\n- ")


if __name__ == "__main__":
    main()
