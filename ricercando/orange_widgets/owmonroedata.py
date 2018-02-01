import re
import os
import pickle
import concurrent.futures
import logging
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime

import numpy as np
import pandas as pd

from AnyQt.QtWidgets import (
    QApplication, QDateTimeEdit, QLabel, QCheckBox,
    qApp,
)
from AnyQt.QtGui import QValidator, QIntValidator
from AnyQt.QtCore import Qt, QThread, Slot, QItemSelection, QDateTime, Signal

from Orange.data import Table
from Orange.misc.environ import cache_dir
from Orange.widgets import widget, settings, gui
from Orange.widgets.utils.itemmodels import PyTableModel
from Orange.widgets.utils.concurrent import (
    ThreadExecutor, FutureWatcher, methodinvoke
)

from ricercando import (
    set_connection_params, all_nodes, tables_for_node,
    table_timerange, distinct_values, all_tables,
    getdf,
)
from ricercando.query_base import _ALLOWED_FREQS
from ricercando.orange_widgets.util import table_from_frame


log = logging.getLogger(__name__)


class CachedNodeInfoTable:
    LIST = os.path.join(cache_dir(), 'owmonroedata', 'nodes_info_list.pickle')
    TABLES = os.path.join(cache_dir(), 'owmonroedata', 'tables.pickle')
    os.makedirs(os.path.dirname(LIST), exist_ok=True)

    @classmethod
    def _load(cls, file):
        with open(file, 'rb') as f:
            return pickle.load(f)

    @classmethod
    def _dump(cls, obj, file):
        with open(file, 'wb') as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load_list(cls):
        return cls._load(cls.LIST)

    @classmethod
    def dump_list(cls, lst):
        cls._dump(lst, cls.LIST)

    @classmethod
    def load_tables(cls):
        return cls._load(cls.TABLES)

    @classmethod
    def dump_tables(cls, lst):
        cls._dump(lst, cls.TABLES)

    @classmethod
    def clear(cls):
        for file in (cls.LIST, cls.TABLES):
            try:
                os.remove(file)
            except FileNotFoundError:
                pass


@contextmanager
def blockSignals(*objects):
    for obj in objects:
        obj.blockSignals(True)
    yield
    for obj in objects:
        obj.blockSignals(False)


class Validator:
    Port = Timeout = QIntValidator

    class Hostname(QValidator):
        def validate(self, p_str, _, _regex=re.compile(r'^\w[\w.-]*[^.-]$')):
            if '..' in p_str:
                return self.Invalid
            return self.Acceptable if _regex.match(p_str) else self.Invalid


class OWMonroeData(widget.OWWidget):
    name = 'MONROE Data'
    description = 'Import MONROE node data from an OLAP database.'
    icon = 'icons/category.svg'
    priority = 90

    class Outputs(widget.OWWidget.Outputs):
        data = widget.Output('Data', Table)

    want_main_area = True
    want_control_area = True

    auto_commit = settings.Setting(True)

    con_hostname = settings.Setting('192.168.27.75')
    con_port = settings.Setting('8086')
    con_username = settings.Setting('monroe')
    con_password = settings.Setting('secure')
    con_database = settings.Setting('monroe')
    con_timeout = settings.Setting(60)

    sample_size = settings.Setting(2000)
    included_data = settings.Setting({'event', 'ping', 'gps', 'modem', 'sensor'})

    LABEL_CONNECT = 'Co&nnect && Update Node Info'
    LABEL_DOWNLOAD = '&Download Selected'
    LABEL_CANCEL = '&Cancel'

    DATE_FORMATS = ('yyyy-MM-dd', 'HH:mm')
    PYDATE_FORMAT = '%Y-%m-%d %H:%M'
    RESOLUTION = OrderedDict([
        ('10 milliseconds', '10ms'),
        ('1 second', '1s'),
        ('1 minute', '1m'),
        ('30 minutes', '30m'),
    ])
    assert all(v in _ALLOWED_FREQS
               for v in RESOLUTION.values())

    INTERPOLATION = OrderedDict([
        ('no interpolation', False),
        ('linear', 'linear'),
        ('fill-forward', 'ffill'),
        ('nearest', 'nearest'),
    ])

    sample_resolution = settings.Setting(next(iter(RESOLUTION.keys())))
    sample_interpolation = settings.Setting('linear')
    sample_ts_from = settings.Setting(pd.Timestamp('2017-01-01').timestamp())
    sample_ts_to = settings.Setting(pd.Timestamp.now(tz=None).timestamp())

    selection = settings.Setting([], schema_only=True)  # FIXME: doesn't work


    class Information(widget.OWWidget.Information):
        fetching_node_info = widget.Msg('Fetching available node information ...')

    class Error(widget.OWWidget.Error):
        fetching_node_info_failed = widget.Msg('Fetching node data failed: {}')

    def __init__(self):
        self.model = None

        self._task = None  # type: Optional[self.Task]
        self._executor = ThreadExecutor(self)
        self.is_downloading = False

        box = gui.vBox(self.controlArea, 'Database Connection')
        gui.lineEdit(box, self, 'con_hostname', label='Hostname:',
                     orientation=Qt.Horizontal, validator=Validator.Hostname())
        gui.lineEdit(box, self, 'con_port', label='Port:',
                     orientation=Qt.Horizontal, validator=Validator.Port())
        gui.lineEdit(box, self, 'con_username', label='Username:',
                     orientation=Qt.Horizontal)
        edit = gui.lineEdit(box, self, 'con_password', label='Password:',
                     orientation=Qt.Horizontal)
        edit.setEchoMode(edit.Password)
        gui.lineEdit(box, self, 'con_database', label='Database:',
                     orientation=Qt.Horizontal)
        gui.spin(box, self, 'con_timeout', 5, 300, 5, label='Timeout [s]:')
        self.btn_connect = gui.button(box, self, self.LABEL_CONNECT,
                                      callback=self.load_data)

        box = gui.vBox(self.controlArea, 'Download')

        def _dateTimeChanged(editted):
            def handler():
                minTime = self.date_from.dateTime().toMSecsSinceEpoch() / 1000
                maxTime = self.date_to.dateTime().toMSecsSinceEpoch() / 1000
                if minTime > maxTime:
                    minTime = maxTime = minTime if editted == self.date_from else maxTime

                    other = self.date_to if editted == self.date_from else self.date_from
                    with blockSignals(other):
                        other.setDateTime(editted.dateTime())

                    self.btn_download.setEnabled(minTime != maxTime)

                # Update saved settings
                self.sample_ts_from = minTime
                self.sample_ts_to = maxTime

            return handler

        kwargs = dict(calendarPopup=True,
                      displayFormat=' '.join(self.DATE_FORMATS),
                      timeSpec=Qt.UTC)
        date_from = self.date_from = QDateTimeEdit(self, **kwargs)
        date_to = self.date_to = QDateTimeEdit(self, **kwargs)
        date_from.setDateTime(QDateTime.fromMSecsSinceEpoch(self.sample_ts_from * 1000, Qt.UTC))
        date_to.setDateTime(QDateTime.fromMSecsSinceEpoch(self.sample_ts_to * 1000, Qt.UTC))
        date_from.dateTimeChanged.connect(_dateTimeChanged(date_from))
        date_to.dateTimeChanged.connect(_dateTimeChanged(date_to))

        hbox = gui.hBox(box)
        hbox.layout().addWidget(QLabel('From:'))
        hbox.layout().addWidget(date_from)
        hbox = gui.hBox(box)
        hbox.layout().addWidget(QLabel('To:'))
        hbox.layout().addWidget(date_to)

        self.box_include_data = gui.vBox(box, 'Include')

        gui.spin(box, self, 'sample_size', 100, 20000, 100, label='Sample size:')
        gui.comboBox(box, self, 'sample_resolution',
                     label='Resolution:',
                     orientation=Qt.Horizontal,
                     items=tuple(self.RESOLUTION.keys()),
                     sendSelectedValue=True)
        gui.comboBox(box, self, 'sample_interpolation',
                     label='Interpolation:',
                     orientation=Qt.Horizontal,
                     items=tuple(self.INTERPOLATION.keys()),
                     sendSelectedValue=True)

        self.btn_download = gui.button(box, self, self.LABEL_DOWNLOAD,
                                       callback=self.download)
        gui.rubber(self.controlArea)

        ## Main area

        class Model(PyTableModel):
            def update_row(self, i, row):
                self[i] = row

        model = self.model = Model(parent=self)
        model.setHorizontalHeaderLabels(
            ['Node Id', 'Interfaces', 'Start Time', 'Stop Time', 'Available Data'])
        view = self.view = gui.TableView(self)
        view.horizontalHeader().setStretchLastSection(False)
        view.setModel(self.model)
        self.mainArea.layout().addWidget(view)

        # Restore node info table from cache, if any
        try:
            lst = CachedNodeInfoTable.load_list()
        except Exception:
            pass  # Cache not exists
        else:
            model.wrap(lst)

        # Restore tables checkboxes from cache
        try:
            tables = CachedNodeInfoTable.load_tables()
        except Exception:
            pass
        else:
            for table in tables:
                self.box_include_data.layout().addWidget(
                    QCheckBox(table, self, checked=table in self.included_data))

        # Establish default database connection from settings
        set_connection_params(self.con_hostname, self.con_port,
                              self.con_username, self.con_password,
                              self.con_database, timeout=self.con_timeout)

    def load_data(self):
        # Make sure any pending tasks are cancelled.
        if self._task is not None:
            self.cancel()
            return

        self.btn_download.setEnabled(False)
        self.setCursor(Qt.BusyCursor)
        self.btn_connect.setText(self.LABEL_CANCEL)
        self.Information.fetching_node_info()
        self.Error.fetching_node_info_failed.clear()

        CachedNodeInfoTable.clear()

        set_connection_params(self.con_hostname, self.con_port,
                              self.con_username, self.con_password,
                              self.con_database, timeout=self.con_timeout)

        lst = [[node] + [''] * 4
               for node in all_nodes()]

        # Add tables checkboxes into Download section
        layout = self.box_include_data.layout()
        while True:  # Purge existing
            item = layout.takeAt(0)
            if not item:
                break
            item.widget().setParent(None)
        for table in all_tables():
            layout.addWidget(QCheckBox(table, self, checked=table in self.included_data))
        CachedNodeInfoTable.dump_tables(all_tables())

        set_progress = methodinvoke(self, "setProgressValue", (float,))

        self._task = task = self.Task()
        self.progressBarInit()

        def func():
            FREQ = '30m'

            min_time = pd.Timestamp('2100-01-01')
            max_time = pd.Timestamp('1800-01-01')

            for i, row in enumerate(lst):
                if task.cancelled:
                    raise self.Cancelled

                node = row[0]
                tables = tables_for_node(node)
                times = np.array([table_timerange(table, node, freq=FREQ)
                                  for table in tables])

                tmin = times[:, 0].min().tz_convert(None)  # tz_convert strips '+00:00'
                tmax = times[:, 1].max().tz_convert(None)
                min_time = min(min_time, tmin)
                max_time = max(max_time, tmax)

                row[0] = int(node)
                row[1] = ', '.join(sorted(distinct_values('modem', 'Interface',
                                                          nodeid=node, freq=FREQ)))
                row[2] = '' if pd.isnull(tmin) else tmin.strftime(self.PYDATE_FORMAT)
                row[3] = '' if pd.isnull(tmax) else tmax.strftime(self.PYDATE_FORMAT)
                row[4] = ', '.join(tables)

                set_progress(i / len(lst) * 99)

            return lst, min_time, max_time

        task.future = self._executor.submit(func)
        task.watcher = FutureWatcher(task.future)
        task.watcher.done.connect(self.node_info_complete)

    def cancel(self):
        """
        Cancel the current task (if any).
        """
        if self._task is not None:
            self._task.cancel()
            assert self._task.future.done()
            # disconnect the `_task_finished` slot
            # self._task.watcher.done.disconnect(self._task_finished)
            self._task = None

    @Slot(concurrent.futures.Future)
    def node_info_complete(self, future):
        assert self.thread() is QThread.currentThread()
        assert future.done()

        self._task = None
        self.progressBarFinished()

        self.setCursor(Qt.ArrowCursor)
        self.btn_connect.setText(self.LABEL_CONNECT)
        self.Information.fetching_node_info.clear()

        try:
            lst, min_time, max_time = future.result()  # type: Tuple[List[List], pd.Timestamp, pd.Timestamp]
        except self.Cancelled:
            pass
        except Exception as e:
            log.exception("Error fetching node info")
            self.Error.fetching_node_info_failed(e)
        else:
            self.model.wrap(lst)
            CachedNodeInfoTable.dump_list(lst)
            self.btn_download.setEnabled(True)

            # Apply saved row selection
            if self.selection:
                try:
                    selection = QItemSelection()
                    for row in self.model.mapFromSourceRows(self.selection):
                        selection.select(self.model.index(row, 0))
                    self.view.selectionModel().select(selection)
                except Exception:
                    log.exception('Failed to restore selection')
                self.selection = []

            self.date_from.setDateTime(
                QDateTime.fromMSecsSinceEpoch(min_time.timestamp() * 1000, Qt.UTC))
            self.date_to.setDateTime(
                QDateTime.fromMSecsSinceEpoch(max_time.timestamp() * 1000, Qt.UTC))

    @Slot(float)
    def setProgressValue(self, value):
        assert self.thread() is QThread.currentThread()
        self.progressBarSet(value)

    class Task:
        future = ...  # type: concurrent.futures.Future
        watcher = ...  # type: FutureWatcher
        cancelled = False  # type: bool

        def cancel(self):
            self.cancelled = True
            # Cancel the future. Note this succeeds only if the execution has
            # not yet started (see `concurrent.futures.Future.cancel`) ..
            self.future.cancel()
            # ... and wait until computation finishes
            concurrent.futures.wait([self.future])

    class Cancelled(Exception):
        pass

    def download(self):
        if self._task is not None:
            self.cancel()
            return

        self.btn_connect.setEnabled(False)
        self.setCursor(Qt.BusyCursor)
        self.btn_download.setText(self.LABEL_CANCEL)

        # Remember selected tables
        layout = self.box_include_data.layout()
        tables = self.included_data = {
            w.text()
            for w in (layout.itemAt(i).widget()
                      for i in range(layout.count()))
            if w.isChecked()}

        # Remeber selected rows
        rows = [mi.row() for mi in self.view.selectionModel().selectedRows(0)]
        self.selection = rows

        nodes = [self.model[row][0] for row in self.model.mapToSourceRows(rows)]

        self._task = task = self.Task()
        self.progressBarInit()
        set_progress = methodinvoke(self, "setProgressValue", (float,))

        def func():
            if not nodes:
                raise self.Cancelled

            def progress_advance(*_, _counter=0):
                if task.cancelled:
                    raise self.Cancelled
                _counter += 1
                set_progress(_counter / (len(tables) + 1))

            df = getdf(tables,
                       nodeid=nodes,
                       start_time=self.date_from.textFromDateTime(self.date_from.dateTime()),
                       end_time=self.date_to.textFromDateTime(self.date_to.dateTime()),
                       freq=self.RESOLUTION[self.sample_resolution],
                       interpolate=self.INTERPOLATION[self.sample_interpolation],
                       callback=progress_advance)
            return df

        task.future = self._executor.submit(func)
        task.watcher = FutureWatcher(task.future)
        task.watcher.done.connect(self.download_complete)

    @Slot(concurrent.futures.Future)
    def download_complete(self, future):
        assert self.thread() is QThread.currentThread()
        assert future.done()

        self._task = None
        self.progressBarFinished()
        self.setCursor(Qt.ArrowCursor)
        self.btn_download.setText(self.LABEL_DOWNLOAD)
        self.btn_connect.setEnabled(True)
        self.Information.fetching_node_info.clear()

        table = None
        try:
            df = future.result()  # type: pd.DataFrame
        except self.Cancelled:
            pass
        except Exception as e:
            log.exception("Failed to download data for nodes")
            self.Error.fetching_node_info_failed(e)
        else:
            if df.shape[0] > self.sample_size:
                df = df.sample(self.sample_size)
            table = table_from_frame(df)

        self.Outputs.data.send(table)


if __name__ == "__main__":
    a = QApplication([])
    log.setLevel(logging.DEBUG)
    ow = OWMonroeData()
    ow.show()
    a.exec()
