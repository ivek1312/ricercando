from itertools import chain
from functools import lru_cache

import pandas as pd

from .db import _check_table
from .query_base import query, query_async, _check_freq
from .util import aslist


__all__ = ['distinct_values', 'all_nodes', 'all_tables', 'nodes_for_table',
           'tables_for_node', 'table_timerange']


@lru_cache()
def distinct_values(table, field, *,
                    nodeid='', where='', freq='1s',
                    start_time=None, end_time=None):
    """
    Return set of unique `field` values in `table`.

    Parameters
    ----------
    table : str
        Table to query.
    field : str
        Table column to select the values of.
    nodeid : str
        Filter rows by NodeId.
    where : str or list of str
        Additional SQL WHERE conditions.
    freq : str
        The granularity table to query. See `freq` in `getdf()` docstring.
    start_time : str or datetime or pandas.Timestamp
    end_time : str or datetime or pandas.Timestamp

    Returns
    -------
    set
    """
    table = _check_table(table)
    where = aslist(where, str)
    freq = _check_freq(freq)
    if nodeid:
        where.append('NodeId = {!r}'.format(str(int(nodeid))))
    if start_time:
        start_time = pd.Timestamp(start_time).isoformat()
        where.append('time >= {!r}'.format(start_time))
    if end_time:
        end_time = pd.Timestamp(end_time).isoformat()
        where.append('time <= {!r}'.format(end_time))
    results = query('SELECT DISTINCT({field}) FROM {table}_{freq}{where}'.format(
        field=field,
        table=table,
        freq=freq,
        where=(' WHERE ' + ' AND '.join(where)) if where else '',
    ))
    results = {row['distinct'] for row in results.get_points()}
    return results


@lru_cache(1)
def all_nodes():
    """
    Returns
    -------
    list
        List of nodes available in the database.
    """
    nodes = sorted(set(chain.from_iterable(nodes_for_table().values())), key=int)
    return nodes


@lru_cache(1)
def all_tables():
    """
    Returns
    -------
    list
        List of tables available in the database.
    """
    return sorted(nodes_for_table().keys())


@lru_cache(1)
def nodes_for_table():
    """
    Returns
    -------
    dict
        Sorted list of available nodes per each table.
    """
    results = query('SHOW TAG VALUES WITH KEY = NodeId')
    nodes = {measurement.split('_')[0]: sorted(set(row['value'] for row in rows), key=int)
             for (measurement, _), rows in results.items()}
    return nodes


@lru_cache()
def tables_for_node(nodeid):
    """
    Return tables `nodeid` is found in.

    Parameters
    ----------
    nodeid : str or int
        The NodeId to find in tables.

    Returns
    -------
    set
        Tables `nodeid` appears in.
    """
    nodeid = str(int(nodeid))
    return {measurement
            for measurement, nodes in nodes_for_table().items()
            if nodeid in nodes}


@lru_cache()
def table_timerange(table, nodeid='', *, freq='10ms'):
    """
    Return table's min and max timestamp.

    Parameters
    ----------
    table : str
        A table name from ``all_tables()``.
    nodeid : str or int
        The NodeId to limit results for.
    freq : str
        Granularity to query. See `freq` in `getdf()` docstring.

    Returns
    -------
    tuple
        2-tuple of pandas.Timestamp: (start time, end time).
    """
    freq = _check_freq(freq)
    table = _check_table(table)
    where = ' WHERE NodeId = {!r}'.format(str(nodeid)) if nodeid else ''
    queries = [
        'SELECT {field} FROM {table}_{freq}{where} ORDER BY time LIMIT 1'.format(
            field=table._default_field,
            table=table,
            freq=freq,
            where=where),
        'SELECT {field} FROM {table}_{freq}{where} ORDER BY time DESC LIMIT 1'.format(
            field=table._default_field,
            table=table,
            freq=freq,
            where=where),
    ]
    times = pd.to_datetime([row['time']
                            for results in query_async(queries)
                            for _, rows in results.items()
                            for row in rows], unit='ms', utc=True)
    assert not pd.isnull(times.min()) or times.size == 0
    assert not pd.isnull(times.max()) or times.size == 0
    return times.min(), times.max()


def clear_caches():
    for func in __all__:
        globals()[func].cache_clear()
