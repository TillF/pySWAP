from .utils.basemodel import PySWAPBaseModel
from .utils.files import open_file
from typing import Optional, Any
from pathlib import Path
import shutil
import tempfile
import subprocess
import os
from importlib import resources
from pydantic import BaseModel, ConfigDict
from pandas import DataFrame, read_csv, to_datetime
from numpy import nan
from ..soilwater import SnowAndFrost
from .richards import RichardsSettings
from ..extras import HeatFlow, SoluteTransport
from .utils.system import get_base_path, is_windows


class Result(BaseModel):
    summary: Optional[str]
    output: Optional[DataFrame]
    vap: Optional[Any]
    log: Optional[str]

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        extra='forbid'
    )


class Model(PySWAPBaseModel):

    metadata: Any
    simsettings: Any
    meteorology: Any
    crop: Any
    irrigation: Any
    soilmoisture: Any
    surfaceflow: Any
    evaporation: Any
    soilprofile: Any
    snowandfrost: Optional[Any] = SnowAndFrost(swsnow=0, swfrost=0)
    richards: Optional[Any] = RichardsSettings(swkmean=1, swkimpl=0)
    lateraldrainage: Any
    bottomboundary: Any
    heatflow: Optional[Any] = HeatFlow(swhea=0)
    solutetransport: Optional[Any] = SoluteTransport(swsolu=0)

    def write_swp(self, path: str) -> None:
        string = self._concat_sections()
        self.save_element(string=string, path=path,
                          filename='swap', extension='swp')
        print('swap.swp saved.')

    @staticmethod
    def _copy_swap_exe(tempdir: Path):
        # Use a context manager to ensure the temporary file is cleaned up
        with resources.path("pyswap.libs.swap420-exe", "swap.exe") as exec_path:
            shutil.copy(str(exec_path), str(tempdir))
        print('Copying the windows version of SWAP into temporary directory...')

    @staticmethod
    def _copy_swap(tempdir: Path) -> None:
        # Use a context manager to ensure the temporary file is cleaned up
        with resources.path("pyswap.libs.swap420-linux", "swap420") as exec_path:
            shutil.copy(str(exec_path), str(tempdir))
        print('Copying linux executable into temporary directory...')

    @staticmethod
    def _run_exe(tempdir: Path, swap_path=None) -> str:
        if swap_path is None:
            swap_path = Path(tempdir, 'swap.exe') if is_windows() else './swap420'

        p = subprocess.Popen(swap_path,
                             stdout=subprocess.PIPE,
                             stdin=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             cwd=tempdir)

        return p.communicate(input=b'\n')[0].decode()

    @staticmethod
    def _read_log(tempdir: Path):
        log_file = os.path.join(tempdir, 'swap_swap.log')

        with open(log_file, 'r') as f:
            log_data = f.read()
            return log_data

    @staticmethod
    def _read_output(path: Path):
        df = read_csv(path, comment='*', index_col='DATETIME')
        df.index = to_datetime(df.index)

        return df

    @staticmethod
    def _read_vap(path: Path):
        df = read_csv(path, skiprows=11, encoding_errors='replace')
        df.columns = df.columns.str.strip()
        df.replace(r'^\s*$', nan, regex=True, inplace=True)
        return df

    def _write_inputs(self, path: str) -> None:
        print('Preparing files...')
        self.write_swp(path)
        if self.lateraldrainage.drainagefile:
            self.lateraldrainage.write_dra(path)
        if self.crop.cropfiles:
            self.crop.write_crop(path)
        if self.meteorology.meteodata:
            self.meteorology.write_met(path)
        if self.irrigation.fixedirrig:
            if self.irrigation.fixedirrig.irrigationdata:
                self.irrigation.fixedirrig.write_irg(path)

    
    #def run(self, path: str | Path, swap_path=None: str | Path):
    def run(self, path: str | Path, swap_path=None):
        """Main function that runs the model.

        TODO: implement asynchronous function that would run the swap exe and then check once in a few seconds if the swap.log is there.
        If it is there, read it and check status. If status is error, exit the with/while clause.
        TODO: implement catching and printing errors and terminating the with statement if there
        is an error in the model run.
        """
        with tempfile.TemporaryDirectory(dir=path) as tempdir:
            print(tempdir)
            if swap_path is None: #no executable sepcified: copy executable from Python package 
                if is_windows():
                    self._copy_swap_exe(tempdir)
                else:
                    self._copy_swap(tempdir)

            self._write_inputs(tempdir)
            result = self._run_exe(tempdir, swap_path)

            if 'normal completion' not in result:
                raise Exception(
                    f'Model run failed. \n {result}')
            else:
                print(result)

                result = Result(
                    summary=open_file(Path(tempdir, 'result.blc')),
                    output=self._read_output(
                        Path(tempdir, 'result_output.csv')),
                    vap=self._read_vap(Path(tempdir, 'result.vap')),
                    log=self._read_log(tempdir)
                )

                return result
