from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError, InfluxDBServerError


InfluxDBException = (InfluxDBClientError,
                     InfluxDBServerError)


def set_connection_params(host: str = 'localhost',
                          port: int = 8086,
                          username: str = 'monroe',
                          password: str = 'secure',
                          database: str = 'monroe',
                          timeout: int = 60,
                          **kwargs):
    """Set default parameters passed to influxdb.DataFrameClient"""
    global _host, _port, _username, _password, _database, _timeout, _kwargs
    _host = host or 'localhost'
    _port = port
    _username = username
    _password = password
    _database = database
    _timeout = max(1, int(timeout))
    _kwargs = kwargs
    # Reset client
    global _client
    _client = None

    # Connection params have changed, clear caches
    try:
        from .queries import clear_caches
        clear_caches()
    except ImportError:
        # Fails on _this_ module import when set_connection_params
        # is initially called
        pass


def get_client() -> InfluxDBClient:
    """ Returns influxdb.DataFrameClient instance """
    global _client
    if _client is None:
        _client = InfluxDBClient(host=_host,
                                 port=_port,
                                 username=_username,
                                 password=_password,
                                 database=_database,
                                 timeout=_timeout,
                                 **_kwargs)
    return _client


# Set default variables
_client = _host = _port = _username = _password = _database = _timeout = _kwargs = None
set_connection_params()
