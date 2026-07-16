"""Use PyMySQL as MySQLdb on hosts where mysqlclient cannot be compiled (cPanel)."""
try:
    import pymysql

    pymysql.install_as_MySQLdb()
except ImportError:
    # mysqlclient (or another MySQLdb) may be installed instead
    pass
