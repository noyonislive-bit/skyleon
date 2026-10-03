# Use the pure-Python PyMySQL driver as a drop-in replacement for mysqlclient.
# Shared hosting usually has no C compiler / MySQL headers, so mysqlclient
# cannot be built there; PyMySQL installs everywhere.
try:  # pragma: no cover - import side effect
    import pymysql

    pymysql.install_as_MySQLdb()
except ImportError:  # mysqlclient (or sqlite for tests) may be used instead
    pass
