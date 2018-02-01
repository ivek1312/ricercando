import unittest.mock

import pandas as pd
from influxdb.resultset import ResultSet

from ricercando import getdf, query, query_async
from ricercando import (all_nodes,
                         all_tables,
                         nodes_for_table,
                         tables_for_node,
                         table_timerange)

from ricercando.query_base import _ALLOWED_FREQS


RESULTS = [
    {"measurement": "ping_10ms",
     "tags": {"NodeId": "109", "Iccid": "1234"},
     "columns": ["time", "RTT", 'Operator'],
     "values": [
         [1504210000000, 100, 'Orange'],
         [1504220000000, None, 'Orange'],
         [1504230000000, 150, 'Orange'],
     ]},
    {"measurement": "ping_10ms",
     "tags": {"NodeId": "200", "Iccid": "4321"},
     "columns": ["time", "RTT", 'Operator'],
     "values": [
         [1504210000000, 110, 'Orange'],
         [1504220000000, None, 'Vodafone'],
         [1504230000000, 140, None],
     ]},
    {"measurement": "modem_10ms",
     "tags": {"NodeId": "109", "Iccid": "1234"},
     "columns": ["time", 'RSSI', 'CID'],
     "values": [
         [1504230000000, -65, 123456],
     ]},
    {"measurement": "modem_10ms",
     "tags": {"NodeId": "109", "Iccid": "1234"},
     "columns": ["time", 'RSSI', 'CID'],
     "values": [
         [1504210000000, -88, 450454],
         [1504220000000, -92, None],
     ]},
    {"measurement": "sensor_10ms",
     "tags": {"NodeId": "109"},
     "columns": ["time", 'Uptime'],
     "values": [
         [1504210000000, 100],
         [1504220000000, 110],
     ]},
]

NODEID_TAGS = [
    {'measurement': measurement, 'tags': None,
     'columns': ['value', 'key'],
     'values': [[rs['tags']['NodeId'], 'NodeId']
                for rs in RESULTS
                if rs['measurement'] == measurement]}
    for measurement in set(rs['measurement'] for rs in RESULTS)
]


N_RESULTS = len(RESULTS)
N_ROWS = sum(len(rs['values'])
             for rs in RESULTS)
ALL_NODEIDS = sorted(set([row[0]
                          for rs in NODEID_TAGS
                          for row in rs['values']]))
ALL_TABLES = sorted(set(rs['measurement'].split('_')[0]
                        for rs in NODEID_TAGS))
NODES_PER_TABLE = {rs['measurement'].split('_')[0]: sorted(set(i[0] for i in rs['values']))
                   for rs in NODEID_TAGS}
_ping_times = [row[0]
               for rs in RESULTS
               for row in rs['values']
               if rs['measurement'].startswith('ping_')]
TIMERANGE = [pd.Timestamp(min(_ping_times), unit='ms', tz='UTC'),
             pd.Timestamp(max(_ping_times), unit='ms', tz='UTC')]


class MockedClient:
    def query(self, query, *args, epoch=None, **kwargs):
        assert epoch == 'ms', epoch
        if query.startswith('SHOW '):
            return ResultSet(dict(series=NODEID_TAGS))
        return ResultSet(dict(series=RESULTS))

    def query_async(self, query, *args, **kwargs):
        return self.query(query, *args, **kwargs)


@unittest.mock.patch('ricercando.connection._client', MockedClient())
class TestQuery(unittest.TestCase):
    def test_query(self):
        rs = query('select * from whatever')
        self.assertIsInstance(rs, ResultSet)
        self.assertEqual(len(rs), N_RESULTS)
        self.assertEqual(len(list(rs.get_points())), N_ROWS)

    def test_query_async(self):
        rs = list(query_async(['select * from whatever']))
        self.assertTrue(all(isinstance(rs, ResultSet) for rs in rs))
        self.assertEqual(sum(len(rs) for rs in rs), N_RESULTS)
        self.assertEqual(sum(len(list(rs.get_points())) for rs in rs), N_ROWS)


@unittest.mock.patch('ricercando.connection._client', MockedClient())
class TestDataFrame(unittest.TestCase):
    def test_data(self):
        df = getdf('ping')
        self.assertEqual(df.shape[0], N_ROWS)

    def test_tables(self):
        getdf('ping')
        getdf('ping,modem')
        getdf('ping modem')
        getdf(['ping', 'modem'])
        getdf('ping', nodeid='404')
        getdf('ping', nodeid=['404', '123'])
        self.assertRaises(ValueError, getdf, 'nonexisting')
        self.assertRaises(ValueError, getdf, 'nonexisting, ping')

    def test_where(self):
        getdf('ping', where='NodeId = "123"')
        getdf('ping', where=["NodeId = '123'", 'Mode = 1'])

    def test_time(self):
        getdf('ping', start_time='2016', end_time='2017')
        self.assertRaises(ValueError, getdf, 'ping', start_time='2017', end_time='2010')

    def test_freq(self):
        for freq in _ALLOWED_FREQS:
            getdf('ping', freq=freq)
        self.assertRaises(ValueError, getdf, 'ping', freq='x')

    @unittest.skip('Known to fail with test data. ICBA. See: GH-pandas#17093')
    def test_resample(self):
        df = getdf('ping', resample='1s')
        self.assertEqual(df.index.rule_code, 'M')

    def test_interpolate(self):
        n_null = getdf('ping').isnull().sum().sum()
        for method in ('linear', 'ffill', 'bfill', True):
            df = getdf('ping', interpolate=method)
            # Less nulls than if uninterpolated
            self.assertLess(df.isnull().sum().sum(), n_null)


@unittest.mock.patch('ricercando.connection._client', MockedClient())
class TestQueries(unittest.TestCase):
    def test_queries(self):
        self.assertEqual(all_nodes(), sorted(ALL_NODEIDS))
        self.assertEqual(all_tables(), sorted(ALL_TABLES))
        self.assertEqual(nodes_for_table(), NODES_PER_TABLE)
        self.assertEqual(tables_for_node(109), {'modem', 'sensor', 'ping'})
        self.assertSequenceEqual(table_timerange('ping'), TIMERANGE)


if __name__ == '__main__':
    unittest.main()
