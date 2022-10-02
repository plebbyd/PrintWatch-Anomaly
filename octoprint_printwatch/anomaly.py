from enum import Enum
from threading import Thread
from time import time, sleep
from math import pi, sqrt, exp

class OutlierHandler():

    def __init__(self, intervals : list = [10, 100, 1000]):
        self.intervals = intervals
        self.outlier_counts = [0. for i in intervals]

    def count_outliers(self, rows : list, interval : int) -> list:
        return [ele[1] for ele in rows].count(True) #this allows for index 0 to be the raw output function score of the server response

    def count_intervals_outliers(self, rows : list) -> list:
        return False
    def std_comparison(self, std : float = 3.) -> list:
        return False
    def compute_std(self):
        return False

    def compute_mean():
        return False
    def gaussian_density_function(self, input : float, interval) -> float:
        return 1/(sqrt(2*pi()) * self.sigma[self.intervals.index(interval)]) *exp(-1 * (input - self.mu[self.intervals.index(interval)])**2/(2 * self.sigma[self.intervals.index(interval)]**2))


    #During a print job, the overall job interval should be considered for defectiveness
    #And also the local defectiveness of perhaps the trailing N data




class SMADataType():

    def __init__(self, size):
        #Format for this dataype is:
        #[Total summation for the inference cycle, Running total, Total inferences]
        self.buffer = [[0, 0, 0]]
        self.size = size

    def sma(self, num):
        return sum([i[0] for i in self.buffer[-num:] ]) / num

    def add(self, ele):
        while len(self.buffer) >= self.size:
            self.buffer.pop(0)

        self.buffer.append([ele, self.buffer[-1][1] + ele, self.buffer[-1][2] + 1])


class States(Enum):
    OPEN_SERIAL = 0
    DETECT_SERIAL = 1
    DETECT_BAUDRATE = 2
    CONNECTING = 3
    OPERATIONAL = 4
    PRINTING = 5
    PAUSED = 6
    CLOSED = 7
    ERROR = 8
    CLOSED_WITH_ERROR = 9
    TRANSFERING_FILE = 10
    OFFLINE = 11
    UNKNOWN = 12
    NONE = 13

class BadRowException(Exception):
    def __init__(self, e):
        self.message = f"{e}"

class AnomalyFeatures():
    def __init__(self):
        self.rows_of_data = [] #N=22 features at the moment

    def append_row(self, row : list):
        if isinstance(row, list):
            self.rows_of_data.append(row)
        else:
            raise BadRowException('row must be of type <list> and size=26')

    def retrieve_row(self, idx : int = -1) -> list:
        return self.rows_of_data[idx]

    def retrieve_all_data(self) -> list:
        return self.rows_of_data




class AnomalyDetector():

    def __init__(self, plugin):
        self.plugin = plugin
        self.samples = AnomalyFeatures()
        self.last_time = 0.0
        self.tool_change_time = 0.0
        self.filament_change_time = 0.0
        self.current_feedrate_percent = 1.0
        self.current_feedrate = 1.0
        #self.sma = SMADataType()
        self.acquire_samples()
        self.start_thread()

    def acquire_samples(self):
        current_data = self.plugin._printer.get_current_data()
        current_temps = self.plugin._printer.get_current_temperatures()
        self.plugin._logger.info('TEMPS" {}'.format(current_temps))
        files = self.plugin._file_manager.list_files()
        current_file_name = current_data['job']['file']['name']
        lanks = self.get_lankyness_XYZ(current_file_name)

        assembled_row = [
            States[self.plugin._printer.get_state_id()].value,
            int(current_data['state']['flags']['sdReady']),
            int(self.check_last_same_job_success(current_file_name)) if current_file_name and current_file_name is not '' else 0,
            current_data['progress']['printTime'] if current_data['progress']['printTime'] else 0.0,
            current_data['currentZ'] if current_data['currentZ'] else 0.0,
            lanks[0],
            lanks[1],
            lanks[2],
            current_data['resends']['ratio'],
            int(time() - self.filament_change_time < 300.0),
            int(time() - self.tool_change_time < 300.0),
            self.current_feedrate,
            self.current_feedrate_percent,
            current_temps['bed']['actual'] if current_temps.get('bed') and current_temps.get('bed') is not None else 0.0,
            current_temps['bed']['target'] if  current_temps.get('bed') and current_temps.get('bed') is not None else 0.0,
            current_temps['bed']['offset'] if  current_temps.get('bed') and current_temps.get('bed') is not None else 0.0,
            current_temps['chamber']['actual'] if current_temps.get('chamber') and current_temps.get('chamber').get('actual') else 0.0,
            current_temps['chamber']['target'] if current_temps.get('chamber') and current_temps.get('chamber').get('target') is not None else 0.0,
            current_temps['chamber']['offset'] if current_temps.get('chamber') and current_temps.get('chamber').get('offset') else 0.0
            ]
        _num_extruders = self.plugin._printer_profile_manager.get_current().get('extruder').get('count', 1)
        for tool_num in range(_num_extruders):
            assembled_row.append(current_temps['tool{}'.format(tool_num)]['actual'] if current_temps.get('tool{}'.format(tool_num)) else 0.0)
            assembled_row.append(current_temps['tool{}'.format(tool_num)]['target'] if current_temps.get('tool{}'.format(tool_num)) else 0.0)
            assembled_row.append(current_temps['tool{}'.format(tool_num)]['offset'] if current_temps.get('tool{}'.format(tool_num)) else 0.0)
        self.plugin._logger.info('New add"n: {}'.format(assembled_row))
        self.samples.append_row(assembled_row)

    def get_lankyness_XYZ(self, filename):
        if filename and filename is not '':
            file_info = self.plugin._file_manager.list_files()['local'][filename]['analysis']['dimensions']
            XY = file_info['width'] / file_info['depth']
            YZ = file_info['depth'] / file_info['height']
            XZ = file_info['width'] / file_info['height']
        else:
            XY = 0.0
            YZ = 0.0
            XZ = 0.0
        return [XY, YZ, XZ]

    def check_last_same_job_success(self, filename):
        files = self.plugin._file_manager.list_files()
        file_info = files['local'][filename]
        last_job_info = file_info['history'][-1]
        return last_job_info['success']

    def start_thread(self):
        self.run_thread = True
        self.anomaly_loop = Thread(target=self._sampling)
        self.anomaly_loop.daemon = True
        self.anomaly_loop.start()

    def _sampling(self):
        while True:
            if time() - self.last_time > 2.0:
                self.acquire_samples()
                self.last_time = time()
                self.plugin._logger.info('SIZE: {}'.format(len(self.samples.rows_of_data)))
                if len(self.samples.rows_of_data)%10==0:
                    self.plugin._logger.info(self.samples.rows_of_data[-10:])
                    self.plugin.comm_manager.send_anomaly()
                    '''
                    with open('output_file.txt', 'w+') as f:
                        for line in self.samples.rows_of_data:
                            f.write("%s\n" % str(line).replace('[', '').replace(']', ''))
                    '''

            sleep(0.2)
