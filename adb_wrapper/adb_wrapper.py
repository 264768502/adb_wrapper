# -*- coding: utf-8 -*-
import sys
import os
import time
import re
import posixpath
import subprocess

from .base_wrapper import Queue, Empty, Thread, Event
from .base_wrapper import shlex
from .base_wrapper import BaseWrapper
from .base_wrapper import ignored
from .base_wrapper import IS_PY2
from .base_wrapper import _enqueue_output
from .base_wrapper import _to_unicode, _to_utf8
from .base_wrapper import ON_POSIX
from .base_wrapper import FILE_TYPES
from .base_wrapper import BINARY_ENC as ADB_ENC
from .base_wrapper import FILE_TRANSFORM_TIMEOUT, BUGREPORT_TIMEOUT
from .base_wrapper import _device_checkor
from .base_wrapper import PERMISSION_DENY, TIMEOUT, DEVICE_OFFLINE, NOFILEORFOLDER, READONLY, SHELL_FAILED
from .base_wrapper import SubprocessException, NoDeviceException

THIRDADB = ('tadb.exe', 'ShuameDaemon.exe', 'shuame_helper.exe',
            'wpscloudlaunch.exe', 'AndroidServer.exe', 'Alipaybsm.exe',
            'TaobaoProtect.exe', 'wpscenter.exe', 'wpscloudsvr.exe')
ADBGAP = 0.25  # Default blocking command check gap for command terminate
ADBIP_PORT = int(os.getenv('ADBPORT', '5555'))  # Default adb network device port, should keep align with adb
ADB_SERVER_PORT = 5037  # Default adb server local port


class AdbFailException(SubprocessException):
    def __init__(self, msg=None, stdout=None, stderr=None):
        super(AdbFailException, self).__init__(msg, stdout, stderr)
        self.msg, self.stdout, self.stderr = msg, stdout, stderr

class AdbConnectFail(AdbFailException):
    pass

class AdbNoDevice(AdbFailException):
    pass

class AdbTimeout(AdbFailException):
    pass

class AdbShell(object):
    '''
    AdbShell, offer easy write/read command for short adb shell process.
    It should be created by AdbWrapper.shell_unblock
    This class can only handle short shell communicate, all stdout/stderr
    will in memory
    '''
    def __init__(self, process, logger):
        self.logger = logger
        self.p = process
        self.stdout_q = Queue()
        self.stdout_stop = Event()
        self.stdout_t = Thread(target=_enqueue_output,
                               args=(self.p.stdout, self.stdout_q, self.stdout_stop, self.logger))
        self.stdout_t.daemon = True
        self.stdout_t.start()
        self.stderr_q = Queue()
        self.stderr_stop = Event()
        self.stderr_t = Thread(target=_enqueue_output,
                               args=(self.p.stderr, self.stderr_q, self.stderr_stop, self.logger))
        self.stderr_t.daemon = True
        self.stderr_t.start()

    def __del__(self):
        self.kill()

    def process(self):
        '''
        Output: Popen Process
        '''
        return self.p

    def isalive(self):
        '''
        adb shell subprocess status
        Output: True/False
        '''
        self.p.poll()
        if self.p.returncode is None:
            return True
        else:
            return False

    def _read(self, q):
        out = ''
        while 1:
            try:
                out = q.get_nowait()
                self.logger.debug("out: {!r}".format(out))
            except Empty:
                break
            else:
                out += out
        return out

    def read_stdout(self):
        '''
        Output: stdout (str)
        '''
        self.logger.info("AdbShell stdout Read")
        return self._read(self.stdout_q)

    def read_stderr(self):
        '''
        Output: stdout (str)
        '''
        self.logger.info("AdbShell stderr Read")
        return self._read(self.stderr_q)

    def write(self, cmd):
        '''
        Input: cmd (str)[Format should be ADB_ENC] or (Unicode)
        '''
        self.logger.info("AdbShell Write: {!r}".format(cmd))
        self.p.stdin.write(_to_utf8(cmd))

    def kill(self):
        self.p.poll()
        if self.p.returncode is None:
            with ignored(OSError):
                self.p.kill()
            self.p.wait()
        if self.stdout_t.isAlive():
            self.stdout_stop.set()
            self.stdout_t.join()
        if self.stderr_t.isAlive():
            self.stderr_stop.set()
            self.stderr_t.join()


class AdbLogcat(object):
    '''
    AdbLogcat, offer easy handle for adb logcat process
    It should be created by AdbWrapper.logcat
    Offer below function:
        isalive()
        join()
        close()
        filename()
    '''
    def __init__(self, process, filename, logger):
        self.logger = logger
        self.p = process
        self.name = filename
        if self.p.stderr:
            self.p.stderr.close()
        self.logger.info("Adblogcat({}): start".format(self.name))

    def __del__(self):
        self.close()

    def isalive(self):
        '''
        adb shell/logcat subprocess status
        Output: True/False
        '''
        self.logger.info("Adblogcat({}): isalive".format(self.name))
        self.p.poll()
        if self.p.returncode is None:
            return True
        else:
            return False

    def join(self, timeout=None):
        '''
        Similar as Threading's join, block until process stop
        Input: timeout (int/float/None[infinite])
        Output: True [Process exist] / False [Timeout]
        '''
        self.logger.info("Adblogcat({}): join".format(self.name))
        self.p.poll()
        start_time = time.time()
        if timeout is None:
            _timeout = 99999999
        else:
            _timeout = timeout
        while self.p.returncode is None and time.time() - start_time < _timeout:
            self.p.poll()
            time.sleep(ADBGAP)
        return not self.isalive()

    def filename(self):
        return self.name

    def close(self):
        self.logger.info("Adblogcat({}): close".format(self.name))
        self.p.poll()
        if self.p.returncode is None:
            with ignored(OSError):
                self.logger.info("Adblogcat({}): kill adb process".format(self.name))
                self.p.kill()
            self.p.wait()
            self.logger.debug("Adblogcat({}): adb logcat close".format(self.name))
        if self.p.stdout:
            self.p.stdout.close()


class AdbWrapper(BaseWrapper):
    '''
    This is a Google Android adb wrapper (adb.exe/adb).
    It can offer basic connect, disconnect, shell, and etc.
    Support both Windows/Ubuntu Python2/Python3
    Verified at Windows7/Ubuntu16 Python2.7.11/Python3.5.1
    Note: All input cmd should be str(Encoding should be ADB_ENC) or Unicode
    After run any adb command, there will be a adb daemon in backgroud created by adb automatically
    To kill it manually, you need use kill_server
    '''

    thirdbinary_p = THIRDADB
    _binaryname = u'adb'
    nodevice_re_list = [u'waiting for device', u'error: device \s+ not found']
    devices_re = re.compile(r'([0-9a-zA-Z_:.-]*)\s*(device|unauthorized|offline|sideload)')
    adb_error_re = re.compile(r'error: (.*)')
    pm_failure_re = re.compile(r'Failure \[(.*)\]')
    pull_pattern = re.compile(r'pull: .* -> (.*)')

    def __init__(self, adb_file=None, logger=None, adb_server_port=ADB_SERVER_PORT):
        super(AdbWrapper, self).__init__(adb_file, logger)
        self._adb_server_port = adb_server_port
        self.logger.info("AdbWrapper: init complete")

    @property
    def adb_server_port(self):
        return self._adb_server_port

    # TODO: define wrong command if command_blocking

    def _adbcommand_unblocking(self, cmdlist, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE):
        '''
        Run adb command unblocking
        Input: cmdlist(list), stdout/stderr(same as subprocess.Popen), timeout(int/float)
        Output: Result(bool) / P(Popen/str)
        if Result = True (No exception happen or subprocess verify quickly), P = Popen
        else, Result = False, P = Reason
        '''
        _cmdlist = self._cmdlist_convert(cmdlist)
        stdout_str, stderr_str = '', ''
        ret = True
        reason = ''
        try:
            p = subprocess.Popen(_cmdlist, stdin=stdin, stdout=stdout, stderr=stderr,
                                 bufsize=1, close_fds=ON_POSIX)
        except (OSError, ValueError) as e:
            self.logger.error("Run adb command Exception")
            self.logger.error("Exception: {!r}".format(e))
            stderr_str = u"{}".format(e)
            if isinstance(stderr, FILE_TYPES):
                stderr.write(stderr_str.encode(ADB_ENC))
            ret = False
            reason = u'OSError or ValueError'
        except Exception as err:
            self.logger.error("Run adb command unknown Exception")
            self.logger.error("Exception: {!r}".format(err))
            self.logger.exception("Stack: ")
            stderr_str = u"{}".format(err)
            if isinstance(stderr, FILE_TYPES):
                stderr.write(stderr_str.encode(ADB_ENC))
            ret = False
            reason = u'Unknown Exception'
        else:
            p.poll()
            if p.returncode is None:
                ret = True
            else:
                ret = False
                self.logger.error("Create _adbcommand_unblocking error: {}".format(p.returncode))
            self.subproc_list.append(p)
        return ret, p

    def _set_binary_version(self):
        '''
        Get adb tool version
        Output: Result [True/False]
                Version [Result==True](str) / Reason(str)
                stdout/stderr
        '''
        self.logger.info("adb_version: Start")
        cmdlist = ['version']
        stdout, stderr = self._command_blocking(cmdlist)
        pair = re.search(r'Android Debug Bridge version ([0-9.]{1,10})', stdout)
        if pair:
            self.logger.info("adb version: {}".format(pair.group(1)))
            self._binary_version = pair.group(1)
            if self._binary_version != '1.0.32':
                self.logger.warning("This script is for 1.0.32, not sure work or not on other version")
        else:
            self.logger.error("Fail to find adb version pattern")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)

    def start_server(self):
        '''
        Try start adb demon
        Output: Result (bool) / Reason / stdout / stderr
        '''
        self.logger.info("start_server: start")
        cmdlist = ['start-server']
        try:
            stdout, stderr = self._command_blocking(cmdlist)
        except NoDeviceException:
            raise AdbNoDevice(u'', u'', u'')
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'daemon started successfully' in stdout:
            self.logger.info("start-server: success")
        elif stdout == u'' and stderr == u'':
            self.logger.warning("start-server: already start")
        elif u'starting it now on port' in stdout:
            self.logger.info("start-server: success")
        elif u'failed to start daemon' in stdout:
            self.logger.error("start-server: fail. {!r}".format(stdout))
            raise AdbFailException('Fail start server', stdout, stderr)
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("start-server: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        else:
            self.logger.error("start-server: fail with unknown reason, please check stdout/stderr")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException('Unknown error', stdout, stderr)

    def kill_server(self):
        '''
        Try kill adb server
        Output: Result (bool) / Reason / stdout / stderr
        '''
        self.logger.info("kill-server: start")
        cmdlist = ['kill-server']
        try:
            stdout, stderr = self._command_blocking(cmdlist)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if stdout == u'' and stderr == u'':
            self.logger.info("kill-server: success")
        elif u'server not running' in stdout or u'server not running' in stderr:
            self.logger.warning("kill-server: server not running")
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("kill-server: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        else:
            self.logger.error("kill-server: fail with unknown reason, please check stdout/stderr")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException('Unknown error', stdout, stderr)

    def devices(self):
        '''
        Get device list from adb device, blocking operation
        Output: Result [Run command success will be True](bool)
                       [No device will return True too]
                Device Dict [Maybe blank dict if no device](dict) or Reason(str)
                stdout[from adb command](str)
                stderr(str)
        Device Dict: {
                        Device(IP:Port or SN): Status (device/unauthorized/offline),
                        ...
        }
        '''
        self.logger.info("devices: start")
        cmdlist = ['devices']
        try:
            stdout, stderr = self._command_blocking(cmdlist)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("devices: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        devices = self.devices_re.findall(stdout.replace(u'List of devices attached', ''))
        devices_dict = {}
        for device in devices:
            if re.match(r'[^:]+:\d{1,5}', device[0]):
                self.logger.info("Find network device: {device} | {status}".format(device=device[0], status=device[1]))
            else:
                self.logger.info("Find   usb   device: {device} | {status}".format(device=device[0], status=device[1]))
            if device[0] == u'of' and device[1] == u'device':
                continue
            devices_dict.update({device[0]: device[1]})
        return devices_dict

    @_device_checkor
    def connect(self, device=None):
        '''
        Try to adb connect device, blocking operation
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)
        Output: Device(SN or IP:Port)
        PS: USB adb device cannot disconnect
        '''
        self.logger.info("connect: start")
        self.logger.info("connect: target - %s", device)
        device_pattern = re.compile(r'connected to ({device}.*)'.format(device=device))
        cmdlist = ['connect', device]
        try:
            stdout, stderr = self._command_blocking(cmdlist)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'already connected to ' in stdout:
            devicename = device_pattern.search(stdout).group(1).rstrip()
            self.logger.warning("connect: already connected {device}".format(device=devicename))
            self.logger.warning("Sometimes, this status may be fake, it's better to check with shell exit")
        elif u'connected to ' in stdout:
            devicename = device_pattern.search(stdout).group(1).rstrip()
            self.logger.info("connect: success - {device}".format(device=devicename))
        elif u'empty host name' in stdout or u'Name or service not known' in stdout:
            self.logger.error("connect: empty host name/Name or service not known")
            if u':' in device:
                self.logger.info("Try adb connect again without default port %d" % ADBIP_PORT)
                ip = device.split(u':')[0]
                return self.connect(ip)
            raise AdbConnectFail("Connect empty host name/Name or service not known", stdout, stderr)
        elif u'missing port in specification' in stdout:
            return self.connect(device+u':'+str(ADBIP_PORT))
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("connect: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif u'unable to connect to' in stdout:
            self.logger.error("connect: fail")
            raise AdbConnectFail("Connect Fail", stdout, stderr)
        else:
            self.logger.error("connect: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)
        return devicename

    @_device_checkor
    def disconnect(self, device=None):
        '''
        Try to adb disconnect device, blocking operation
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)
        Output: None
        PS: USB adb device cannot disconnect
        '''
        self.logger.info("disconnect: start")
        if not device:
            self.logger.warning("disconnect: no target device, will disconnect all")
            cmdlist = ['disconnect']
        else:
            self.logger.info("disconnect: target - %s", device)
            cmdlist = ['disconnect', device]
        try:
            stdout, stderr = self._command_blocking(cmdlist)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'No such device ' in stdout:
            self.logger.warning("disconnect: No such device - %s", device)
        elif stdout.strip() == u'' and stderr == u'':
            self.logger.info("disconnect: success - %s", device)
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("disconnect: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        else:
            self.logger.error("disconnect: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)

    @_device_checkor
    def bugreport(self, filename=None, device=None, timeout=BUGREPORT_TIMEOUT):
        '''
        Try get adb bugreport
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filename [Write bugreport into file]
        Output: bugreport(bugreport str and filename=None /
                          full filepath filename!=None
        '''
        self.logger.info("bugreport: start")
        self.logger.info("bugreport: target - %s", device)
        cmdlist = ['-s', device, 'bugreport']
        try:
            stdout, stderr = self._command_blocking(cmdlist=cmdlist, timeout=timeout)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                self.logger.warning("bugreport timeout")
            else:
                raise
        if u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("bugreport: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        if sys.platform == 'win32':
            bugreport_str = stdout.replace(u'\r\r\n', u'\r\n').encode(ADB_ENC)
        else:
            bugreport_str = stdout.encode(ADB_ENC)
        if filename:
            with open(filename, 'ab') as f:
                f.write(bugreport_str)
                self.logger.info("bugreport: Write to file success - {}".format(os.path.abspath(filename)))
                return os.path.abspath(filename)
        else:
            return bugreport_str

    @_device_checkor
    def push(self, src, dst, device=None, timeout=FILE_TRANSFORM_TIMEOUT):
        '''
        Try adb push src to dst
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               src/dst[can be file/folder absolute/relative path](str)
               timeout(int/float)
               Support all adb push support method
        Output: None
        User should know file path after push
        From push command, cannot judgement dst is folder or file
        '''
        self.logger.info("push: start")
        self.logger.info("push: target - %s", device)
        cmdlist = ['-s', device, 'push', src, dst]
        try:
            stdout, stderr = self._command_blocking(cmdlist=cmdlist, timeout=timeout)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'Permission denied' in stderr or u'Permission denied' in stdout:
            self.logger.error("push: Permission denied")
            raise AdbFailException(PERMISSION_DENY, stdout, stderr)
        elif u'Read-only file system' in stderr:
            self.logger.error("push: Read-only file system")
            raise AdbFailException(READONLY, stdout, stderr)
        elif u'No such file or directory' in stderr:
            self.logger.error("push: {}".format(NOFILEORFOLDER))
            raise AdbFailException(NOFILEORFOLDER, stdout, stderr)
        elif u'failed to copy' in stderr:
            reason = u'Fail to copy'
            self.logger.error("push: Other fail to copy error")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(reason, stdout, stderr)
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("push: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif u'bytes in' in stderr or u'0 files skipped' in stderr or \
            u'bytes in' in stdout or u'0 files skipped' in stdout:
            self.logger.info("push: success")
        else:
            self.logger.error("push: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)

    @_device_checkor
    def pull(self, src, dst, device=None, timeout=FILE_TRANSFORM_TIMEOUT):
        '''
        Try adb pull src to dst
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               src/dst[can be file/folder absolute/relative path](str)
               timeout(int/float)
               Support all adb pull support method
        Output: filelist
        '''
        self.logger.info("pull: start")
        self.logger.info("pull: target - %s", device)
        cmdlist = ['-s', device, 'pull', src, dst]
        try:
            stdout, stderr = self._command_blocking(cmdlist=cmdlist, timeout=timeout)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'Permission denied' in stderr or u'Permission denied' in stdout:
            self.logger.error("pull: Permission denied")
            raise AdbFailException(PERMISSION_DENY, stdout, stderr)
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("push: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif u'does not exist' in stderr or u'No such file or directory' in stderr:
            self.logger.error("pull: {}".format(NOFILEORFOLDER))
            self.logger.warning("Sometimes this causes by no permission")
            raise AdbFailException(NOFILEORFOLDER, stdout, stderr)
        elif u'0 files pulled' in stderr:
            self.logger.warning("pull: 0 files pulled")
            return []
        elif u'bytes in' in stderr or u'bytes in' in stdout  or u'0 files skipped' in stderr:
            self.logger.info("pull: success")
        else:
            self.logger.error("pull: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)
        if u'files pulled' in stderr:
            # Pull folder
            filelist = self.pull_pattern.findall(stderr.replace(u'\r', u''))
            dstlist = [os.path.abspath(file_path) for file_path in filelist]
            if len(dstlist) == 0:
                self.logger.warning("pull: No file pull, may src is folder without file")
        else:
            # Pull Single file
            if os.path.isdir(dst):
                # dst is folder
                dstlist = [os.path.abspath(os.path.join(dst, posixpath.basename(src)))]
            else:
                # dst not folder
                dstlist = [os.path.abspath(dst)]
        return dstlist

    @_device_checkor
    def remount(self, device=None):
        '''
        Do adb remount (normally it will remount /system to rw)
        remount request root first
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("remount: start")
        self.logger.info("remount: target - %s", device)
        cmdlist = ['-s', device, 'remount']
        try:
            stdout, stderr = self._command_blocking(cmdlist)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'Operation not permitted' in stdout \
           or u'Not running as root' in stdout \
           or u'Permission denied' in stdout:
            self.logger.error("remount: fail - %s", device)
            self.logger.warning("remount: maybe need root first")
            raise AdbFailException(PERMISSION_DENY, stdout, stderr)
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("remount: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif u'remount failed' in stdout:
            self.logger.error("remount: other error - %r", stdout)
            raise AdbFailException('Remount Fail', stdout, stderr)
        elif stdout == u'' or u'remount succeeded' in stdout:
            self.logger.info("remount: success")
        else:
            self.logger.error("remount: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)

    @_device_checkor
    def root(self, device=None):
        '''
        Do adb root (normally it will restart adbd on device, need reconnect for ip/auto reconnect for USB)
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("root: start")
        self.logger.info("root: target - %s", device)
        cmdlist = ['-s', device, 'root']
        try:
            stdout, stderr = self._command_blocking(cmdlist)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("root: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif u'adb: unable to connect for ' in stderr:
            error = re.search(r'adb: unable to connect for [\w]*?: (.*)', stderr).group(1)
            self.logger.error('root: error. %s', error)
            raise AdbFailException(error, stdout, stderr)
        elif u'adb: error while reading for ' in stderr:
            error = re.search(r'adb: error while reading for [\w]*?: (.*)', stderr).group(1)
            self.logger.error('root: error. %s', error)
            raise AdbFailException(error, stdout, stderr)
        elif u'adb: unexpected output length' in stderr:
            self.logger.error("root: unexpected output length")
            raise AdbFailException('unexpected output length', stdout, stderr)
        elif u'adbd cannot run as root in production builds' in stdout:
            self.logger.error("root: Production Builds not support root - %s", device)
            raise AdbFailException(u'production builds not support root', stdout, stderr)
        elif stdout == u'restarting adbd as root' or stdout == u'':
            self.logger.info("root: success")
        elif u'adbd is already running as root' in stdout:
            self.logger.warning("root: already running as root")
        else:
            self.logger.error("root: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)

    @_device_checkor
    def unroot(self, device=None):
        '''
        Do adb unroot (normally it will restart adbd on device, need reconnect for ip/auto reconnect for USB)
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("unroot: start")
        self.logger.info("unroot: target - %s", device)
        cmdlist = ['-s', device, 'unroot']
        try:
            stdout, stderr = self._command_blocking(cmdlist)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("unroot: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif u'adb: unable to connect for ' in stderr:
            error = re.search(r'adb: unable to connect for [\w]*?: (.*)', stderr).group(1)
            self.logger.error('unroot: error. %s', error)
            raise AdbFailException(error, stdout, stderr)
        elif u'adb: error while reading for ' in stderr:
            error = re.search(r'adb: error while reading for [\w]*?: (.*)', stderr).group(1)
            self.logger.error('unroot: error. %s', error)
            raise AdbFailException(error, stdout, stderr)
        elif u'adb: unexpected output length' in stderr:
            self.logger.error("unroot: unexpected output length")
            raise AdbFailException('unexpected output length', stdout, stderr)
        elif u'error' in stdout:
            self.logger.error("unroot: error - %s", device)
            self.logger.error("Maybe your target is not userdebug build")
            raise AdbFailException('Unknown error', stdout, stderr)
        elif u'restarting adbd as non root' in stdout or stdout == '':
            self.logger.info("unroot: success")
        elif u'adbd not running as root' in stdout:
            self.logger.warning("unroot: already in unroot")
        else:
            self.logger.error("unroot: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)

    @_device_checkor
    def reboot(self, mode=None, device=None):
        '''
        Do adb reboot (Normal|bootloader|recovery|sideload|fastboot)
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               mode [None(for normal reboot) / bootloader / recovery /
                     sideload(require root) / sideload-auto-reboot / fastboot]
        Output: None
        '''
        self.logger.info("reboot: start")
        if not mode:
            _mode = u'normal'
            cmdlist = ['-s', device, 'reboot']
        else:
            _mode = _to_unicode(mode)
            cmdlist = ['-s', device, 'reboot', _mode]
        self.logger.info("reboot {mode}: target - {device}".format(mode=_mode, device=device))
        try:
            stdout, stderr = self._command_blocking(cmdlist, timeout=3)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                stdout, stderr = err.stdout, err.stderr
            else:
                raise
        if u'\'adb root\' is required for \'adb reboot sideload\'.' in stdout:
            self.logger.error("reboot: %s", PERMISSION_DENY)
            raise AdbFailException(PERMISSION_DENY, stdout, stderr)
        elif DEVICE_OFFLINE in stderr:
            self.logger.error("reboot: {}".format(DEVICE_OFFLINE))
            raise AdbFailException(DEVICE_OFFLINE, stdout, stderr)
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("reboot: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        else:
            self.logger.warning("reboot: always treat as success")

    @_device_checkor
    def reboot_bootloader(self, device=None):
        return self.reboot(mode=u'bootloader', device=device)

    @_device_checkor
    def shell(self, cmd, device=None, timeout=None):
        '''
        Do adb shell with autoexit command
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               cmd (str)
               timeout [int/float/None(infinite)]
        Output: stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("shell(block): start")
        if IS_PY2:
            cmdlist = ['-s', device, 'shell', '{}'.format(_to_utf8(cmd))]
        else:
            cmdlist = ['-s', device, 'shell', '{}'.format(_to_unicode(cmd))]
        self.logger.info("shell(block): target - %s", device)
        self.logger.info("shell(block): cmd - %s", cmd)
        try:
            stdout, stderr = self._command_blocking(cmdlist, timeout=timeout)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise AdbFailException(err.msg, err.stdout, err.stderr)
        if u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("reboot: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        self.logger.info("shell(block): success")
        return stdout, stderr

    @_device_checkor
    def shell_unblock(self, cmd, device=None):
        '''
        !!!!!!!!!! Still cannot work well after testing !!!!!!!!!!
        Do adb shell with non-autoexit command, need short/easy communicate
        For long shell command, please use another command ## TODO
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               cmd (str)
        Output: Result(bool)
                Reason(str[Result == False]) / AdbShell[Result == True]
        '''
        self.logger.info("shell(unblock): start")
        self.logger.info("shell: target - %s", device)
        if IS_PY2:
            cmdlist = ['-s', device, 'shell'] + ['{}'.format(_to_utf8(cmd))]
        else:
            cmdlist = ['-s', device, 'shell'] + ['{}'.format(_to_unicode(cmd))]
        res = self._adbcommand_unblocking(cmdlist)
        if res[0] != True:
            return res
        else:
            return res[0], AdbShell(res[1], self.logger)

    @_device_checkor
    def install(self, apkfile, forward=False, replace=False, test=False,
                sdcard=False, downgrade=False, permission=False,
                timeout=FILE_TRANSFORM_TIMEOUT, device=None):
        '''
        Do adb install
        Input: apkfile [apk file path](str)
               forward: [-l: forward lock application](bool)
               replace [-r: replace existing application](bool)
               test [-t: allow test packages](bool)
               sdcard [-s: install application on sdcard](bool)
               downgrade [-d: allow version code downgrade](bool)
               permission [-g: grant all runtime permissions](bool)
               timeout (int/float)
               device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        Note: Some Android System need press OK for verify application
              Sugguest close this option in Android System first before use adb install
              (adb shell put global package_verifier_include_adb 0)
              Or you need ignore this function return and wait timeout
        '''
        self.logger.info("install: start")
        self.logger.info("install: target - %s", device)
        self.logger.info("apk: {}".format(os.path.abspath(apkfile)))
        cmdlist = ['-s', device, 'install']
        if forward: cmdlist.append('-l')
        if replace: cmdlist.append('-r')
        if test: cmdlist.append('-t')
        if sdcard: cmdlist.append('-s')
        if downgrade: cmdlist.append('-d')
        if permission: cmdlist.append('-g')
        cmdlist.append(os.path.abspath(apkfile))
        try:
            stdout, stderr = self._command_blocking(cmdlist, timeout=timeout)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'No APK file on command line' in stderr:
            reason = u'No APK file on command line'
            self.logger.error("install: %s", reason)
            raise AdbFailException(reason, stdout, stderr)
        elif u'Filename doesn\'t end .apk' in stderr:
            reason = u'Filename doesn\'t end .apk'
            self.logger.error("install: %s", reason)
            raise AdbFailException(reason, stdout, stderr)
        elif u'Failed to stat' in stderr:
            reason = stderr[stderr.find(u'Failed to stat'):]
            self.logger.error("install: %s", reason)
            raise AdbFailException(reason, stdout, stderr)
        elif u'Failed to open' in stderr:
            reason = stderr[stderr.find(u'Failed to open'):]
            self.logger.error("install: %s", reason)
            raise AdbFailException(reason, stdout, stderr)
        elif u'Connect error for write' in stderr:
            reason = stderr[stderr.find(u'Connect error for write'):]
            self.logger.error("install: %s", reason)
            raise AdbFailException(reason, stdout, stderr)
        elif u'failed to copy' in stderr:
            reason = u'failed to copy'
            self.logger.error("install: {!r}".format(reason))
            raise AdbFailException(reason, stdout, stderr)
        elif u'Failure' in stdout:
            reason = self.pm_failure_re.search(stdout[stdout.find('Failure'):]).group(1)
            self.logger.error("install: {!r}".format(reason))
            raise AdbFailException(reason, stdout, stderr)
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("install: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif u'Success' in stdout or u'Success' in stderr:
            self.logger.info("install: success")
        else:
            self.logger.error("install: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)

    @_device_checkor
    def uninstall(self, package, keepdata=False,
                  timeout=FILE_TRANSFORM_TIMEOUT, device=None):
        '''
        Do adb uninstall
        Input: package [Application package name](str)
               keepdata: [-k: keep data and cache](bool)
               device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("uninstall: start")
        self.logger.info("uninstall: target - %s", device)
        self.logger.info("package: {}".format(package))
        cmdlist = ['-s', device, 'uninstall']
        if keepdata:
            cmdlist.append('-k')
        cmdlist.append(package)
        try:
            stdout, stderr = self._command_blocking(cmdlist, timeout=timeout)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'Failure' in stdout:
            reason = self.pm_failure_re.search(stdout[stdout.find('Failure'):]).group(1)
            self.logger.error("uninstall: {!r}".format(reason))
            raise AdbFailException(reason, stdout, stderr)
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("uninstall: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif u'Success' in stdout:
            self.logger.info("uninstall: success")
        else:
            self.logger.error("uninstall: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)

    def wait_for_device(self, timeout=None):
        '''
        Do adb wait-for-device, blocking untill timeout
        Input: timeout (int/float/None)
        Output: None
        '''
        self.logger.info("wait-for-device")
        cmdlist = ['wait-for-device']
        try:
            stdout, stderr = self._command_blocking(cmdlist, timeout=timeout)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if 'adb: couldn\'t parse \'wait-for\' command' in stderr:
            reason = 'Fail parse wait-for'
            self.logger.error("wait-for-device: %s", reason)
            raise AdbFailException(reason, stdout, stderr)
        elif 'adb: unknown type' in stderr:
            reason = 'Unknown Device Type'
            self.logger.error("wait-for-device: %s", reason)
            raise AdbFailException(reason, stdout, stderr)
        elif 'adb: unknown state' in stderr:
            reason = 'Unknown Device State'
            self.logger.error("wait-for-device: %s", reason)
            raise AdbFailException(reason, stdout, stderr)
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("wait-for-device: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif stdout == '' and stderr == '':
            self.logger.info("wait-for-device: success")
        else:
            self.logger.error("wait-for-device: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)

    @_device_checkor
    def disable_verity(self, device=None):
        '''
        Do adb disable-verity (Need root first)
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("disable-verity: start")
        self.logger.info("disable-verity: target - %s", device)
        cmdlist = ['-s', device, 'disable-verity']
        try:
            stdout, stderr = self._command_blocking(cmdlist)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'disable-verity only works for userdebug builds' in stdout:
            self.logger.error("disable-verity: disable-verity only works for userdebug builds - {}".format(device))
            raise AdbFailException(u"disable-verity only works for userdebug builds", stdout, stderr)
        elif u'Failed to open' in stdout:
            self.logger.error("disable-verity: Fail to open, Maybe non-root?")
            raise AdbFailException(PERMISSION_DENY, stdout, stderr)
        elif u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("disable-verity: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif stdout == u'' or u'Verity disabled on' in stdout:
            self.logger.info("disable-verity: success")
        elif u'Verity already disabled' in stdout:
            self.logger.warning("disable-verity: already disabled")
        else:
            self.logger.error("disable-verity: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)

    @_device_checkor
    def enable_verity(self, device=None):
        '''
        Do adb enable-verity, if success, need reboot to take effect
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("enable-verity: start")
        self.logger.info("enable-verity: target - %s", device)
        cmdlist = ['-s', device, 'enable-verity']
        try:
            stdout, stderr = self._command_blocking(cmdlist)
        except NoDeviceException:
            raise AdbNoDevice
        except SubprocessException as err:
            if err.msg == TIMEOUT:
                raise AdbTimeout(err.msg, err.stdout, err.stderr)
            else:
                raise
        if u'error: ' in stderr:
            error = self.adb_error_re.search(stderr).group(1)
            self.logger.error("enable-verity: error. %s", error)
            raise AdbFailException(error, stdout, stderr)
        elif u'Failed to open' in stdout:
            self.logger.error("enable-verity: Fail to open, Maybe non-root?")
            raise AdbFailException(PERMISSION_DENY, stdout, stderr)
        elif u'error' in stdout:
            self.logger.error("enable-verity: error - %s", device)
            self.logger.error("Maybe your target is not userdebug build")
            raise AdbFailException(u'Error', stdout, stderr)
        elif u'Verity enabled on' in stdout or stdout == '':
            self.logger.info("enable-verity: success")
        elif u'Verity already enabled' in stdout or stdout == '':
            self.logger.warning("enable-verity: already enabled")
        else:
            self.logger.error("enable-verity: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            raise AdbFailException(u'unknown reason', stdout, stderr)

    @_device_checkor
    def logcat(self, filename, params=None, device=None):
        '''
        Do adb logcat, save stdout to filename
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filename [Full file path](str)
               params [logcat's params, see logcat --help, but don't use -f](str)
        Output: Result(bool)
                Reason(str[Result == False]) / AdbLogcat[Result == True]
        '''
        self.logger.info("logcat: start")
        self.logger.info("logcat: target - %s", device)
        if params:
            cmdlist = ['logcat'] + shlex.split(params)
        else:
            cmdlist = ['logcat']
        try:
            filehandler = open(filename, 'ab')
        except IOError:
            return False, u'Open {} Error'.format(filename)
        self.logger.info("logcat: file - {}".format(filename))
        self.logger.info("logcat: params - {}".format(params))
        res = self._adbcommand_unblocking(cmdlist, stdout=filehandler)
        if res[0] != True:
            filehandler.close()
            return res
        else:
            return True, AdbLogcat(res[1], filename, self.logger)

    @_device_checkor
    def shell2file(self, filename, cmd, device=None):
        '''
        Do adb shell cmd, save stdout to filename
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filename [Full file path](str)
               cmd [Any command can run in adb shell such as dmesg/top](str)
        Output: Result(bool)
                Reason(str[Result == False]) / AdbLogcat[Result == True]
        '''
        self.logger.info("shell2file: start")
        self.logger.info("shell2file: target - %s", device)
        cmdlist = shlex.split('shell {}'.format(cmd))
        self.logger.info("shell2file: cmd - {}".format(' '.join(cmdlist)))
        try:
            filehandler = open(filename, 'ab')
        except IOError:
            return False, u'Open {} Error'.format(filename)
        self.logger.info("shell2file: file - {}".format(filename))
        res = self._adbcommand_unblocking(cmdlist, stdout=filehandler)
        if res[0] != True:
            filehandler.close()
            return res
        else:
            return True, AdbLogcat(res[1], filename, self.logger)

# TODO: Different Server Port support with -P
# TODO: new adb wait-for[-<transport>]-<state>
#          wait for device to be in the given state:
#          device, recovery, sideload, or bootloader
#          Transport is: usb, local or any [default=any]
# TODO: adb keygen <file> - generate adb public/private key. The private key is stored in <file>,
#           and the public key is stored in <file>.pub. Any existing files
#           are overwritten.
# TODO: adb sideload <file> - sideloads the given package
# TODO: adb usb - restarts the adbd daemon listening on USB
# TODO: adb tcpip <port> - restarts the adbd daemon listening on TCP on the specified port
