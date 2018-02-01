import re
import logging
from functools import reduce, partial
from concurrent import futures
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np
from pandas.api.types import is_numeric_dtype

from influxdb.resultset import ResultSet
from requests.exceptions import RequestException

from .connection import get_client, InfluxDBException, _timeout
from .util import aslist, asstr
from .db import _check_table, _CATEGORICAL_COLUMNS, AGGREGATE
from . import db


__all__ = ['query', 'query_async', 'getdf']


log = logging.getLogger(__name__)


def query(query: str, **kwargs) -> ResultSet:
    """
    Fetch results of a raw SQL query.

    Parameters
    ----------
    query : str
        An SQL query to fetch results for.
    kwargs :
        Passed to ``influxdb.client.InfluxDBClient``.

    Returns
    -------
    influxdb.resultset.ResultSet
    """
    try:
        client = get_client()
    except InfluxDBException:
        log.exception('Failed to instantiate InfluxDB client:')
        raise
    kwargs.setdefault('epoch', 'ms')
    try:
        log.debug('Executing query: %s', query)
        result = client.query(query, **kwargs)
        log.debug('Result set size: %d, %d rows', len(result), len(tuple(result.get_points())))
        return result
    except RequestException:
        log.error('Failed to execute query in %d seconds: %s', _timeout, query)
        raise
    except InfluxDBException:
        log.error('Failed to execute query: %s', query)
        raise


def query_async(queries: list, callback=None, **kwargs) -> ResultSet:
    """
    Generator fetching results of SQL queries in an asynchronous manner.

    Parameters
    ----------
    queries : list of str
        An list of SQL queries to fetch results for.
    callback : callable
        The function to call after each successfully executed query.
    kwargs :
        Passed to ``influxdb.client.InfluxDBClient``.

    Yields
    ------
    influxdb.resultset.ResultSet
    """
    if isinstance(queries, str):
        queries = [queries]
    with ThreadPoolExecutor(max_workers=len(queries)) as executor:
        try:
            for future in as_completed((executor.submit(query, query_str, **kwargs)
                                        for query_str in queries),
                                       # +1 to allow InfluxDBClient (requests) to fail first
                                       timeout=_timeout + 1):
                yield future.result()

                if callback:
                    callback()

        except (futures.TimeoutError, RequestException):
            log.error("Failed to execute all queries in %d seconds: %s", _timeout, queries)
            raise


def _query_str(table, *, freq, columns='', where='', resample='', limit=1000):
    parts = ['SELECT {columns} FROM {table}_{freq}'.format(
        columns=asstr(columns) or (table._select_agg() if resample else '*'),
        table=str(table),
        freq=freq)]
    if where:
        where = aslist(where, str)
        parts.append('WHERE ' + ' AND '.join(where))

    if resample:
        resample = 'time({}), '.format(resample)

    parts.append('GROUP BY ' + (resample + table._groupby()).lstrip(','))

    if limit:
        parts.append('LIMIT ' + str(int(limit)))

    query_str = ' '.join(parts)
    return query_str


def getdf(tables, *, nodeid='', where='', limit=100000,
          start_time=None, end_time=None,
          freq=None, resample='',
          interpolate=False,
          callback=None) -> pd.DataFrame:
    """
    Return MONROE data as Pandas DataFrame.

    Parameters
    ----------
    tables : str or list of str
        Table name(s) to query and merge. Tables can be from the list
        as retuend by ``all_tables()``.
    nodeid : int or str or list of int or str
        A single node ID or a list thereof. If empty, results for all
        available nodes are returned.
    where : str or list of str
        Additional SQL WHERE conditions.
    limit : int
        Hard-limit on the number of rows requested from the DB for each
        NodeId.
    start_time : str or datetime or pandas.Timestamp
        Query results after start time. Default is set to 14 days before
        `end_time` or the min timestamp of `tables`, whichever is later.
    end_time : str or datetime or pandas.Timestamp
        Query results before end time. Default is set to now or the
        max timestamp of `tables`, whichever is sooner.
    freq : str, from {'10ms', '1s', '1m', '30m'}
        The level of detail to query. Higher precision results in MORE
        data. By default, `freq` is set to a sensible (manageable) value
        based on query time span.
    resample : str
        Resampling rule (such as '1h', '2h', '1d', ...) from
        http://pandas.pydata.org/pandas-docs/stable/timeseries.html#offset-aliases
    interpolate : str or bool, default False
        Interpolation method supported by ``pandas.DataFrame.interpolate``,
        or ``True`` for `linear` interpolation of missing values.
        Rows are grouped by NodeId,Iccid before interpolation.
    callback : callable
        The function to call after each successfully executed query.

    Returns
    -------
    pandas.DataFrame
    """
    tables = list(map(_check_table, aslist(tables)))
    if not tables:
        raise ValueError('Need a table name to fetch')

    if where and isinstance(where, str):
        where = [where]
    where = aslist(where or [], str)

    if nodeid:
        nodeid = aslist(nodeid, str)
        nodedid_where = ['NodeId = {!r}'.format(str(node))
                         for node in nodeid]
        where.append('(' + ' OR '.join(nodedid_where) + ')')

    # Sanitize input date and time
    start_time, end_time = _check_time(start_time, end_time, tables=tables)
    where.append('time >= {!r}'.format(start_time.isoformat()))
    where.append('time <= {!r}'.format(end_time.isoformat()))

    # Determine correct level-of-detail table
    freq = _check_freq(freq, tspan=end_time - start_time, nodeid=nodeid)

    def _where_field_name(condition, _identifiers=re.compile(r'\w+').findall):
        return _identifiers(condition)[0]

    def _query_for_table(table, where, freq, limit, columns=''):
        table_columns = {'time'} | set(table._columns())
        _where = [cond for cond in where
                  if _where_field_name(cond) in table_columns]
        return _query_str(table, columns=columns, freq=freq, where=_where, limit=limit)

    # Construct queries with their applicable "where" parameters
    queries = [_query_for_table(table, where, freq, limit)
               for table in tables]

    # If output will contain column Iccid, ensure it also contains modem.Interface
    if db.modem not in tables and any('Iccid' in table for table in tables):
        queries.append(_query_for_table(db.modem, where, freq, limit,
                                        columns=['Interface', 'Iccid']))

    # Construct response data frames; One df per measurement per tag
    dfs = []
    for results in query_async(queries, callback=callback):
        df = _result_set_to_df(results)
        if df is not None:
            dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    # Join all tables on intersecting columns, namely 'time', 'NodeId', 'IccId', ...
    df = reduce(partial(pd.merge, how='outer', copy=False), dfs)
    del dfs

    # Transform known categorical columns into Categoricals
    for col in df:
        if col in _CATEGORICAL_COLUMNS:
            df[col] = df[col].astype('category')
            # Strip trailing '.0' in categoricals constructed from floats (ints upcasted via NaNs)
            categories = df[col].cat.categories
            if is_numeric_dtype(categories):
                df[col].cat.categories = categories.astype(int).astype(str)
        else:
            # Avoid None values resulting in object dtype
            df[col].fillna(np.nan, inplace=True)

    # Index by time
    df.time = pd.to_datetime(df.time, unit='ms')
    df.set_index('time', inplace=True)
    df.sort_index(inplace=True)

    if resample and not df.empty:
        df = _resample(df, resample)

    if interpolate:
        df = _interpolate(df, interpolate)

    return df


def _get_grouped(df: pd.DataFrame, by):
    by = (df.columns & by).tolist()
    return df.groupby(by, sort=False) if by else df


def _resample(df: pd.DataFrame, rule):
    assert df.index.is_all_dates
    # Group by categorical values and resample each group
    by = df.columns & _CATEGORICAL_COLUMNS
    resampled = _get_grouped(df, by).resample(rule)
    have_numeric_cols = len(by) != df.columns.size

    if have_numeric_cols:
        df = resampled.agg({col: AGGREGATE[col]
                            for col in df
                            if col in AGGREGATE
                            and col not in _CATEGORICAL_COLUMNS})
    else:
        # Size to run the aggregation pipeline, but then discard counts
        # right away, retaining only the resampled-grouped index
        df = resampled.size().to_frame()[[]]  # No columns

    # Groupby puts group keys as index; revert this to timestamp-only index
    df.reset_index(inplace=True)
    df.set_index('time', inplace=True)
    df.sort_index(inplace=True)  # Temporal index scrambed b/c all other index levels
    return df


def _result_set_to_df(result_set: ResultSet):
    dfs = []
    for (measurement, tags), rows in result_set.items():
        df = pd.DataFrame(list(rows))

        for tag, value in tags.items():
            df[tag] = value

        df = _check_table(measurement.split('_')[0]).__transform__(df)
        dfs.append(df)
    if not dfs:
        return None
    return pd.concat(dfs, ignore_index=True)


def _interpolate(df: pd.DataFrame, method):
    if method is True:
        method = 'linear'

    # First remove time from index, see:
    # https://github.com/pandas-dev/pandas/issues/16646#issuecomment-326542649
    df.reset_index(inplace=True)

    if method == 'index':
        log.warning("Interpolation by temporal index currently not supported. "
                    "Interpolating by 'linear'.")

    # Group only by NodeId and/or Iccid for interpolation
    grouped = _get_grouped(df, ['NodeId', 'Iccid'])

    def _interpolator(series):
        if method == 'ffill':
            return series.ffill()
        elif method == 'bfill':
            return series.bfill()
        if is_numeric_dtype(series):
            return series.interpolate(method=method,
                                      limit_direction='both')
        return series.ffill()

    # Apply the interpolation to each series within a group
    df = grouped.apply(lambda group: group.apply(_interpolator))

    # GroupBy-Interpolation can for undisclosed reasons (?) result in
    # all-nan rows. We drop them for convenience.
    df.dropna(how='all', inplace=True)

    # Restore temporal index
    df.set_index('time', inplace=True)
    df.sort_index(inplace=True)
    return df


def _check_time(start_time, end_time, tables=()):
    from .queries import table_timerange
    if end_time is None:
        max_time = max((i[1] for i in map(table_timerange, tables) if i),
                       default=pd.Timestamp(np.iinfo(int).max, tz='UTC'))
        end_time = min(pd.Timestamp('now', tz='UTC'), max_time)
    if start_time is None:
        min_time = min((i[0] for i in map(table_timerange, tables) if i),
                       default=pd.Timestamp(0, tz='UTC'))
        start_time = max(pd.Timestamp.fromordinal(end_time.toordinal() - 14, tz='UTC'),
                         min_time)
    start_time = pd.Timestamp(start_time, tz='UTC')
    end_time = pd.Timestamp(end_time, tz='UTC')
    return start_time, end_time


_ALLOWED_FREQS = ('10ms', '1s', '1m', '30m')


def _check_freq(freq, tspan=None, nodeid=None):
    if tspan is not None and tspan.total_seconds() < 0:
        raise ValueError('Start time must be before end time')

    ONE_HOUR = 3600
    ONE_DAY = 24 * ONE_HOUR

    if freq:
        if freq not in _ALLOWED_FREQS:
            raise ValueError('freq must be from {}'.format(_ALLOWED_FREQS))
    else:
        freq = _ALLOWED_FREQS[-1]
        span_secs = tspan.total_seconds()

        limits = (8 * ONE_HOUR,
                  2 * ONE_DAY,
                  32 * ONE_DAY) if nodeid else (ONE_HOUR / 3,
                                                1 * ONE_HOUR,
                                                20 * ONE_HOUR)
        for i, max_secs in enumerate(limits):
            if span_secs < max_secs:
                freq = _ALLOWED_FREQS[i]
                break
    return freq
