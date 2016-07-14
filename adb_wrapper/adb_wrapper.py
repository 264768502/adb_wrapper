# -*- coding: utf-8 -*-
import sys
import locale
import subprocess
import shlex
import os
import re
import time
import posixpath
import logging
from io import open
from threading import Thread, Event

ADB_ENC = 'UTF-8' # Default adb command encode format
ADB_ENV = os.environ
ADB_ENV['PYTHONIOENCODING'] = ADB_ENC
ON_POSIX = 'posix' in sys.builtin_module_names
THIRDADB = ('tadb.exe', 'ShuameDaemon.exe', 'shuame_helper.exe',
            'wpscloudlaunch.exe', 'AndroidServer.exe', 'Alipaybsm.exe',
            'TaobaoProtect.exe', 'wpscenter.exe', 'wpscloudsvr.exe')

_ver = sys.version_info
is_py2 = (_ver[0] == 2)
is_py3 = (_ver[0] == 3)

if is_py2:
    from distutils.spawn import find_executable as find_executable
    from Queue import Queue, Empty
    from contextlib import contextmanager

    @contextmanager
    def ignored(*exceptions):
        try:
            yield
        except exceptions:
            pass

    file_types = file
    out_coding = ADB_ENC
elif is_py3:
    from shutil import which as find_executable
    from queue import Queue, Empty
    from contextlib import ignored
    from io import IOBase
    file_types = IOBase
    # Python3 always use system encoding to for subprocess.stdout/stderr
    out_coding = locale.getpreferredencoding()
else:
    raise Exception('Unknow Python Version: {ver}'.format(ver=_ver))

ADBGAP = 0.25 # Default blocking command check gap for command terminate
BUGREPORT_TIMEOUT = 300 # Default bugreport timeout
COMMON_BLOCKING_TIMEOUT = 30 # Default common blocking command timeout
COMMON_UNBLOCKING_TIMEOUT = 60 # Default common unblocking command timeout
FILE_TRANSFORM_TIMEOUT = 60 # Default pull/push timeout
ADBIP_PORT = 5555 # Default adb network device port, should keep align with adb
TIMEOUT = u'adb Command Timeout'
NOFILEORFOLDER = u'No Such File or Directory'
PERMISSION_DENY = u'Permission Deny'
DEVICE_OFFLINE = u'error: device offline'
OUT_ERROR_HANDLING = 'ignore' # For Decode Error handling, should be ignore/replace

def _to_unicode(string):
    return string.decode(ADB_ENC) if isinstance(string, bytes) else string

def _to_utf8(string):
    return string if isinstance(string, bytes) else string.encode(ADB_ENC)

def _enqueue_output(out, queue, stop_event, logger):
    '''
    Continues putting subprocess.PIPE data to queue (convert to Unicode before putting)
    '''
    if is_py2:
        while not stop_event.is_set():
            for line in iter(out.readline, b''):
                try:
                    _line = line.decode(out_coding)
                except UnicodeDecodeError:
                    # Sometimes string passthrough wrong data from subprocess, ignore it
                    _line = line.decode(out_coding, OUT_ERROR_HANDLING)
                    logger.critical("UnicodeDecodeError: {!r}".format(line))
                else:
                    logger.debug("line: {!r}".format(_line))
                queue.put(_line)
    elif is_py3:
        while not stop_event.is_set():
            for line in out:
                logger.debug("line: {!r}".format(line))
                try:
                    # Python3 Try Locale Encoding First
                    _line = line.decode(out_coding)
                except UnicodeDecodeError:
                    # If Locale Encoding fail, try ADB_ENC because some command will output UTF8 char
                    _line = line.decode(ADB_ENC, OUT_ERROR_HANDLING)
                    logger.critical("UnicodeDecodeError: {!r}".format(line))
                else:
                    logger.debug("line: {!r}".format(_line))
                queue.put(_line)
    rest = out.read()
    try:
        _rest = rest.decode(out_coding)
    except UnicodeDecodeError:
        _rest = rest.decode(out_coding, OUT_ERROR_HANDLING)
        logger.critical("UnicodeDecodeError: {!r}".format(rest))
    else:
        logger.debug("rest: {!r}".format(_rest))
    queue.put(_rest)
    out.close()

def _device_checkor(func):
    '''
    Check params "device" is valid or not
    '''
    def wrapper(*args, **kwargs):
        if is_py2:
            code = func.func_code
            func_name = func.func_name
        elif is_py3:
            code = func.__code__
            func_name = func.__name__
        names = list(code.co_varnames)
        args_l = list(args)
        num = names.index('device')
        try:
            device = args_l[num]
            args_flag = True # device put in args
        except IndexError:
            device = kwargs.get('device', args[0]._device)
            args_flag = False # device put in kwargs
        if device is None:
            if func_name != 'disconnect':
                args[0].logger.error("Please set_device or set device as params")
                raise Exception("Please set_device or set device as params")
            else:
                return func(*args, **kwargs)
        device = _to_unicode(device)
        if args_flag:
            args_l[num] = device
            new_args = tuple(args_l)
            return func(*new_args, **kwargs)
        else:
            kwargs.update({'device': device})
            return func(*args, **kwargs)
    return wrapper

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
        while True:
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
    def __init__(self, process, filehandler, logger):
        self.logger = logger
        self.p = process
        self.h = filehandler
        self.logger.info("Adblogcat({}): start".format(self.h.name))

    def __del__(self):
        self.p.poll()
        if self.p.returncode is None:
            self.close()
        self.h.close()

    def isalive(self):
        '''
        adb shell/logcat subprocess status
        Output: True/False
        '''
        self.logger.info("Adblogcat({}): isalive".format(self.h.name))
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
        self.logger.info("Adblogcat({}): join".format(self.h.name))
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
        return self.h.name

    def close(self):
        self.logger.info("Adblogcat({}): close".format(self.h.name))
        self.p.poll()
        if self.p.returncode is None:
            with ignored(OSError):
                self.p.kill()
            self.p.wait()
        self.h.close()

class AdbWrapper(object):
    '''
    This is a Google Android adb wrapper (adb.exe/adb).
    It can offer basic connect, disconnect, shell, and etc.
    Support both Windows/Ubuntu Python2/Python3
    Verified at Windows7/Ubuntu16 Python2.7.11/Python3.5.1
    Note: All input cmd should be str(Encoding should be ADB_ENC) or Unicode
    After run any adb command, there will be a adb daemon in backgroud created by adb automatically
    To kill it manually, you need use kill_server
    '''
    def __init__(self, adb_file=None, logger=None):
        if logger is not None:
            self.logger = logger
        else:
            self.logger = logging
            self.logger.basicConfig(format='%(asctime)s %(levelname)-8s %(message)s',
                                    level=logging.INFO)
        self.logger.info("AdbWrapper: init start")
        self.logger.info("Python: {}".format(sys.version))
        self.logger.info("Sys Encoding: {}".format(locale.getpreferredencoding()))
        self._adb = None # Don't set/get _adb directly, please use set_adbfile/get_adbfile
        self._device = None # Don't set/get _device directly, please use set_device/get_device
        self.adblist = [] # Save all adb process by this class (Popen)
        self.adb_version = None
        if adb_file is not None:
            if not self.set_adbfile(adb_file):
                raise Exception("Fail to set adb")
        else:
            if not self._adb_autoset():
                raise Exception("Fail to set adb")
        self.logger.info("AdbWrapper: init complete")

    def __del__(self):
        '''
        User should explicit call (del AdbWrapper class) to avoid some adb process issue
        '''
        self.logger.info("Kill All adb process created by this class")
        for p in self.adblist:
            if p.returncode is None:
                self.logger.warning("PID {} is runing, try to kill it".format(p.pid))
                with ignored(OSError):
                    p.kill()
        self.logger.info("All adb process is clean")

    def _adb_autoset(self):
        '''
        Try to find adb in system
        1. Check exist process list, if exist, set it
        2. Check System PATH
        3. Check Environment ANDROID_HOME
        If find, set it by self.adb_file()
        Output: Result (bool)
        '''
        self.logger.info("adb path auto set: start")
        adb_path = None
        while True:
            res = self.get_adbinprolist()
            if res:
                for pid, proc in res.items():
                    self.logger.info("Find: {pid!5s} {proc}".format(pid=pid, proc=proc))
                    if adb_path is None:
                        adb_path = proc
                        self.logger.info("find adb in exist process list")
                    else:
                        if adb_path != proc:
                            self.logger.warning("find multi runing adb process")
                break

            res = find_executable('adb')
            if res is not None:
                adb_path = res
                self.logger.info("find adb in system $PATH")
                break

            if "ANDROID_HOME" in os.environ:
                filename = 'adb.exe' if sys.platform == 'win32' else 'adb'
                res = os.path.join(os.environ['ANDROID_HOME'], "platform-tools", filename)
                if os.path.exists(res):
                    adb_path = res
                    self.logger.info("find adb in $ANDROID_HOME: {adb}".format(adb=adb_path))
                    break
            break

        self.logger.info("adb path auto set: end")
        if adb_path is None:
            self.logger.warning("find: fail to find adb in process/PATH/ANDROID_HOME")
            return False
        else:
            self.set_adbfile(adb_path)
            return True

    def get_adbfile(self):
        '''
        Return _adb file string
        '''
        self.logger.info("get_adbfile: {adb}".format(adb=self._adb))
        return self._adb

    @property
    def adb_file(self):
        return self.get_adbfile()

    @adb_file.setter
    def set_adbfile(self, adb_file):
        '''
        Set adb_file to self._adb
        '''
        self.logger.info("Set _adb: {adb}".format(adb=adb_file))
        if os.path.isfile(adb_file):
            if os.path.basename(adb_file).lower() not in (u'adb', u'adb.exe'):
                raise Exception("adbfile must be name as adb or adb.exe")
            self._adb = _to_unicode(adb_file)
            self._adb_version()
            return True
        else:
            self.logger.error("adb file no exist: {}".format(adb_file))
            return False

    @property
    def adb_version(self):
        return self._adb_version

    def get_adbinprolist(self):
        '''
        return adb proc_dict
        if fail to find adb, return {}
        if error, return None
        proc_dict = {
                        pid(str): proc(str),
                        ...
                    }
        '''
        self.logger.info("get_adbinprolist start")
        proc_dict = {}
        if sys.platform == 'win32':
            # Only Support Win7 or newer (Don't support cygwin)
            cmdlist = shlex.split('wmic process get processid,executablepath')
            try:
                self.logger.info("Windows cmd: {cmd}".format(cmd=' '.join(cmdlist)))
                wmilist = subprocess.check_output(cmdlist)
            except subprocess.CalledProcessError:
                self.logger.error("wmic run error, please check manually in host")
                return None
            pattern = re.compile(r'(.*?) *(\d{1,8})')
            for proline in wmilist.split('\r\n'):
                _ = pattern.search(proline)
                if _ is None:
                    continue
                proc, pid = _.groups()
                if os.path.basename(proc).lower() == 'adb.exe':
                    proc_dict.update({pid:proc})
                for thirdadb_p in THIRDADB:
                    if os.path.basename(proc) == thirdadb_p:
                        self.logger.critical("Find 3rd adb, please uninstall it to prevent unexpected error")
                        self.logger.critical("3rd adb: {}".format(proc))
        elif sys.platform == 'linux2':
            pids = [pid for pid in os.listdir('/proc') if pid.isdigit()]
            for pid in pids:
                try:
                    proc = open(os.path.join('/proc', pid, 'exe'), 'rb').read()
                except IOError:
                    continue
                if os.path.basename(proc) == 'adb':
                    proc_dict.update({pid:proc})
        else:
            raise Exception("Don't support your system: {system}".format(system=sys.platform))
        for pid, proc in proc_dict.items():
            self.logger.info("adb process: pid({pid})|proc({proc})".format(pid=pid, proc=proc))
        self.logger.info("get_adbinprolist complete")
        return proc_dict

    def _cmdlist_convert(self, cmdlist):
        if not isinstance(cmdlist, list):
            _cmdlist = shlex.split(cmdlist)
        else:
            _cmdlist = list(cmdlist)
        _cmdlist.insert(0, self._adb)
        # Both Python2/Python3 request subprocess args as str(but Python2 str is btye, Python3 str is Unicode)
        if is_py2:
            _cmdlist = [_to_utf8(cmd) for cmd in _cmdlist]
            #self.logger.debug("adb command: {}".format(' '.join([cmd.decode(ADB_ENC) for cmd in _cmdlist])))
        elif is_py3:
            _cmdlist = [_to_unicode(cmd) for cmd in _cmdlist]
            #self.logger.debug("adb command: {}".format(' '.join(_cmdlist)))
        return _cmdlist

    def _adbcommand_blocking(self, cmdlist, timeout=COMMON_BLOCKING_TIMEOUT):
        '''
        Run adb command blocking
        Input: cmdlist(list)
               timeout(int/float/None(infinite))
        Output: Result(bool) / Reason(str) / stdout(str) / stderr(str)
        If find stderr != '', Result = False, Reason = stderr
        else, Result = True, Reason = stdout
        Exception, Result = False, Reason = Exception
        Only Push/Pull can ignore stderr, others must check when stderr != ''
        '''
        _cmdlist = self._cmdlist_convert(cmdlist)
        stdout_str, stderr_str = u'', u''
        ret = True
        reason = u''
        start_time = time.time()
        try:
            p = subprocess.Popen(_cmdlist, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 bufsize=1, close_fds=ON_POSIX)
        except (OSError, ValueError) as e:
            self.logger.error("Run adb command Exception")
            self.logger.error("Exception: {!r}".format(e))
            stderr_str = u"{}".format(e)
            ret = False
            reason = u'OSError or ValueError'
        except Exception as e:
            self.logger.error("Run adb command unknown Exception")
            self.logger.error("Exception: {!r}".format(e))
            self.logger.exception("Stack: ")
            stderr_str = u"{}".format(e)
            ret = False
            reason = u'Unknown Exception'
        else:
            self.adblist.append(p)
            _timeout = 999999999 if timeout is None else timeout
            self.logger.debug("adb command timeout: {}".format(_timeout))
            stdout_q = Queue()
            stdout_stop = Event()
            stdout_t = Thread(target=_enqueue_output, args=(p.stdout, stdout_q, stdout_stop, self.logger))
            stdout_t.daemon = True
            stdout_t.start()
            stderr_q = Queue()
            stderr_stop = Event()
            stderr_t = Thread(target=_enqueue_output, args=(p.stderr, stderr_q, stderr_stop, self.logger))
            stderr_t.daemon = True
            stderr_t.start()
            p.poll()
            stdout_list = []
            while p.returncode is None and time.time() - start_time < _timeout:
                # Suppose if too much stdout, there will be no stderr output
                with ignored(Empty):
                    while time.time() - start_time < _timeout:
                        stdout_tmp = stdout_q.get_nowait()
                        self.logger.debug("stdout_str: {!r}".format(stdout_tmp))
                        stdout_list.append(stdout_tmp)
                with ignored(Empty):
                    stderr_list = []
                    while time.time() - start_time < _timeout:
                        stderr_tmp = stderr_q.get_nowait()
                        stderr_list.append(stderr_tmp)
                        self.logger.debug("stderr_str: {!r}".format(stderr_tmp))
                stderr_str += ''.join(stderr_list)
                if re.search(r'error: device \s+ not found', stderr_str) or 'waiting for device' in stderr_str:
                    ret = False
                    reason = u'Device not found'
                    break
                #time.sleep(ADBGAP)
                p.poll()
            if p.returncode is None:
                p.poll()
                with ignored(OSError):
                    # Ignore OSError for No such process when kill it
                    p.kill()
                p.wait()
                ret = False
                if reason == u'':
                    reason = TIMEOUT
            stdout_stop.set()
            stderr_stop.set()
            stdout_t.join()
            stderr_t.join()
            with ignored(Empty):
                while True:
                    stdout_tmp = stdout_q.get_nowait()
                    stdout_list.append(stdout_tmp)
                    self.logger.debug("stdout_str: {!r}".format(stdout_tmp))
            stdout_str = ''.join(stdout_list)
            with ignored(Empty):
                stderr_list = []
                while True:
                    stderr_tmp = stderr_q.get_nowait()
                    stderr_list.append(stderr_tmp)
                    self.logger.debug("stderr_str: {!r}".format(stderr_str))
            stderr_str += ''.join(stderr_list)
            if reason == u'' and u'Android Debug Bridge version' in stderr_str:
                ret = False
                reason = u'Wrong adb command'
            elif reason == u'' and DEVICE_OFFLINE in stderr_str:
                ret = False
                reason = DEVICE_OFFLINE
            # Non-timeout fail
            elif reason == u'' and stderr_str.strip() != u'':
                ret = False
                reason = stderr_str
            # No reason, no stderr, treat as True
            elif reason == u'' and stderr_str.strip() == u'':
                ret = True
                reason = stdout_str
            else:
                ret = False
        return ret, reason.strip(), stdout_str.strip(), stderr_str.strip()

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
            if isinstance(stderr, file_types):
                stderr.write(stderr_str.encode(ADB_ENC))
            ret = False
            reason = u'OSError or ValueError'
        except Exception as e:
            self.logger.error("Run adb command unknown Exception")
            self.logger.error("Exception: {!r}".format(e))
            self.logger.exception("Stack: ")
            stderr_str = u"{}".format(e)
            if isinstance(stderr, file_types):
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
            self.adblist.append(p)
        return ret, p

    def kill_adb_proc(self):
        '''
        From System level to kill all adb process(create by this class)
        '''
        self.logger.info("Kill adb process start")
        p1 = self.adblist
        if p1 == []:
            self.logger.info("there is no adb process found")
            return True
        # Linux: kill -9 PID
        # Windows: taskkill /F /PID PID /PID PID ...
        if sys.platform == 'win32':
            cmd = u'taskkill /F /PID ' + ' /PID '.join(p1)
            self.logger.info("Windows cmd: {cmd}".format(cmd=cmd))
            cmdlist = shlex.split(cmd)
            try:
                res = subprocess.check_output(cmdlist)
            except:
                self.logger.info("Windows Command Exception")
                ## TODO, check taskkill print
        elif sys.platform == 'linux2':
            for pid in p1:
                cmdlist = ['kill', '-9', pid]
                with ignored(Exception):
                    ## TODO, check kill print
                    res = subprocess.check_output(cmdlist)
        else:
            raise Exception("Don't support your system: {system}".format(system=sys.platform))
        return True

    def set_device(self, device):
        '''
        Set default device(str) for adb device command
        device should be SN or IP or IP:PORT
        set device to self._device
        Output: True
        '''
        self._device = _to_unicode(device)
        self.logger.info("set_device: {device}".format(device=self._device))
        ip_pattern = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
        if ip_pattern.match(self._device):
            self.logger.warning("Device is from network without PORT")
            self.logger.warning("Suggust use device from 'connect' to avoid unknown error")
        return True

    def get_device(self):
        '''
        Get instance default device from self._device
        Output: self._device or False
        '''
        if self._device is None:
            self.logger.error("device is not set, please set_device first")
            return False
        self.logger.info("get_device: {device}".format(device=self._device))
        return self._device

    def _adb_version(self):
        '''
        Get adb tool version
        Output: Result [True/False]
                Version [Result==True](str) / Reason(str)
                stdout/stderr
        '''
        self.logger.info("adb_version: Start")
        cmdlist = ['version']
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        r = re.search(r'Android Debug Bridge version ([0-9.]{1,10})', stdout)
        if r:
            self.logger.info("adb version: {}".format(r.group(1)))
            self.adb_version = r.group(1)
            if self.adb_version != '1.0.32':
                self.logger.warning("This script is for 1.0.32, not sure work or not on other version")
            return True, self.adb_version, stdout, stderr
        else:
            return False, u'adb_version: Fail to find', stdout, stderr

    def start_server(self):
        '''
        Try start adb demon
        Output: Result (bool) / Reason / stdout / stderr
        '''
        self.logger.info("start_server: start")
        cmdlist = ['start-server']
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        if u'daemon started successfully' in stdout:
            self.logger.info("start-server: success")
            return True, u'daemon started successfully', stdout, stderr
        elif stdout == u'':
            self.logger.warning("start-server: already start")
            return True, u'adb start-server already start', stdout, stderr
        elif u'starting it now on port' in stdout:
            self.logger.info("start-server: success")
            return True, u'daemon started successfully', stdout, stderr
        elif u'failed to start daemon' in stdout:
            self.logger.error("start-server: fail. {!r}".format(stdout))
            return False, u'failed to start daemon', stdout, stderr
        else:
            self.logger.error("start-server: fail with unknown reason, please check stdout/stderr")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, u'adb start-server fail with unknown reason', stdout, stderr

    def kill_server(self):
        '''
        Try kill adb server
        Output: Result (bool) / Reason / stdout / stderr
        '''
        self.logger.info("kill-server: start")
        cmdlist = ['kill-server']
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        if stdout == u'':
            self.logger.info("kill-server: success")
            return True, u'adb kill-server success', stdout, stderr
        elif u'server not running' in stdout:
            self.logger.warning("kill-server: server not running")
            return True, u'server not running', stdout, stderr
        elif u'error: ' in stdout:
            self.logger.error("kill-server: fail. {!r}".format(stdout))
            return False, u'adb kill-server fail', stdout, stderr
        else:
            self.logger.error("kill-server: fail with unknown reason, please check stdout/stderr")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, u'adb kill-server fail with unknown reason', stdout, stderr

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
        device_pattern = re.compile(r'([0-9a-zA-Z_:.-]*)\s*(device|unauthorized|offline|sideload)')
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        devices = device_pattern.findall(stdout.replace('List of devices attached', ''))
        devices_dict = {}
        for device in devices:
            if re.match(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{1,5}', device[0]):
                self.logger.info("Find network device: {device} | {status}".format(device=device[0], status=device[1]))
            else:
                self.logger.info("Find   usb   device: {device} | {status}".format(device=device[0], status=device[1]))
            if device[0] == u'of' and device[1] == u'device':
                continue
            devices_dict.update({device[0]:device[1]})
        return True, devices_dict, stdout, stderr

    @_device_checkor
    def connect(self, device=None):
        '''
        Try to adb connect device, blocking operation
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)
        Output: Result(bool) / Device(str When Result=True) or Reason(str) / stdout[from adb command](str) / stderr(str)
        PS: USB adb device cannot disconnect
        '''
        self.logger.info("connect: start")
        self.logger.info("connect: target - {device}".format(device=device))
        device_pattern = re.compile(r'connected to ({device}.*)'.format(device=device))
        cmdlist = ['connect', device]
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
        if u'already connected to ' in stdout:
            devicename = device_pattern.search(stdout).group(1).rstrip()
            self.logger.warning("connect: already connected {device}".format(device=devicename))
            self.logger.warning("Sometimes, this status may be fake, it's better to check with shell exit")
            res = True
            reason = devicename
        elif u'unable to connect to' in stdout:
            self.logger.error("connect: fail")
            res = False
            reason = u"adb connect fail"
        elif u'connected to ' in stdout:
            devicename = device_pattern.search(stdout).group(1).rstrip()
            self.logger.info("connect: success - {device}".format(device=devicename))
            res = True
            reason = devicename
        elif u'empty host name' in stdout:
            self.logger.error("connect: empty host name")
            if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:%d$'%ADBIP_PORT, device):
                self.logger.info("Try adb connect again without default port %d"%ADBIP_PORT)
                ip = re.search(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):%d$'%ADBIP_PORT, device).group(1)
                return self.connect(ip)
            res = False
            reason = u"empty host name"
        elif u'error: protocol fault' in stderr:
            reason = stderr
            self.logger.error("connect: {}".format(reason))
        else:
            self.logger.error("connect: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            res = False
            reason = u"adb connect fail with unknown reason"
        return res, reason, stdout, stderr

    @_device_checkor
    def disconnect(self, device=None):
        '''
        Try to adb disconnect device, blocking operation
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)
        Output: Result(bool) / Device(str When Result=True) or Reason(str) / stdout[from adb command](str) / stderr(str)
        PS: USB adb device cannot disconnect
        '''
        self.logger.info("disconnect: start")
        if device is None:
            self.logger.warning("disconnect: no target device, will disconnect all")
            cmdlist = ['disconnect']
        else:
            self.logger.info("disconnect: target - {device}".format(device=device))
            cmdlist = ['disconnect', device]
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        if u'No such device ' in stdout:
            self.logger.warning("disconnect: No such device - {device}".format(device=device))
            return True, "no such device", stdout, stderr
        elif stdout.strip() == u'' and stderr == u'':
            self.logger.info("disconnect: success - {device}".format(device=device))
            return True, device, stdout, stderr
        else:
            self.logger.error("disconnect: fail with unknown reason")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, u"adb disconnect fail with unknown reason", stdout, stderr

    @_device_checkor
    def bugreport(self, filename=None, device=None, timeout=BUGREPORT_TIMEOUT):
        '''
        Try get adb bugreport
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filename [Write bugreport into file]
        Output: Result(bool)
                bugreport(bugreport str When Result=True and filename=None /
                          full filepath When Result=True and filename!=None or Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("bugreport: start")
        self.logger.info("bugreport: target - {device}".format(device=device))
        cmdlist = ['-s', device, 'bugreport']
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist=cmdlist, timeout=timeout)
        if not res and reason != TIMEOUT:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        # elif u'permission denied' in stdout:
        #     self.logger.error("bugreport: Permission denied - {device}".format(device=_device))
        #     return False, PERMISSION_DENY, stdout, stderr
        elif res or reason == TIMEOUT:
            self.logger.info("bugreport: get" + (" but timeout" if reason==TIMEOUT else ""))
            if filename is None:
                return res, TIMEOUT if reason==TIMEOUT else stdout, stdout, stderr
            else:
                with open(filename, 'ab') as f:
                    if sys.platform == 'win32':
                        f.write(stdout.replace(u'\r\r\n', u'\r\n').encode(ADB_ENC))
                    else:
                        f.write(stdout.encode(ADB_ENC))
                    self.logger.info("bugreport: Write to file success - {}".format(os.path.abspath(filename)))
                return res, os.path.abspath(filename), stdout, stderr
        else:
            self.logger.critical("bugreport: unexpected result")
            self.logger.critical("bugreport: res - {0} | reason - {1}".format(res, reason))
            return False, reason, stdout, stderr

    @_device_checkor
    def push(self, src, dst, device=None, timeout=FILE_TRANSFORM_TIMEOUT):
        '''
        Try adb push src to dst
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               src/dst[can be file/folder absolute/relative path](str)
               timeout(int/float)
               Support all adb push support method
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        User should know file path after push
        From push command, cannot judgement dst is folder or file
        '''
        self.logger.info("push: start")
        self.logger.info("push: target - {device}".format(device=device))
        cmdlist = ['-s', device, 'push', src, dst]
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist=cmdlist, timeout=timeout)
        if reason == stderr: # Push complete
            if u'bytes in' in stderr or u'0 files skipped' in stderr:
                self.logger.info("push: success")
                ret = True
                reason = u''
            else:
                ret = False
            if u'Permission denied' in stderr:
                reason = PERMISSION_DENY
                self.logger.error("push: Permission denied")
            elif u'Read-only file system' in stderr:
                reason = u'Read-only file system'
                self.logger.error("push: Read-only file system")
            elif u'No such file or directory' in stderr:
                reason = NOFILEORFOLDER
                self.logger.error("push: {}".format(NOFILEORFOLDER))
            elif u'failed to copy' in stderr:
                reason = u'Fail to copy'
                self.logger.error("push: Other fail to copy error")
                self.logger.error("stdout: {!r}".format(stdout))
                self.logger.error("stderr: {!r}".format(stderr))
            elif reason == DEVICE_OFFLINE:
                self.logger.error("push: {}".format(DEVICE_OFFLINE))
            else:
                if not ret:
                    reason = u'Unknown error'
                    self.logger.error("push: Unknown error")
                    self.logger.error("stdout: {!r}".format(stdout))
                    self.logger.error("stderr: {!r}".format(stderr))
        else: # Other status
            ret = res
        return ret, reason, stdout, stderr

    @_device_checkor
    def pull(self, src, dst, device=None, timeout=FILE_TRANSFORM_TIMEOUT):
        '''
        Try adb pull src to dst
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               src/dst[can be file/folder absolute/relative path](str)
               timeout(int/float)
               Support all adb pull support method
        Output: Result(bool)
                Reason(str) / filelist[Result=True](list)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("pull: start")
        self.logger.info("pull: target - {device}".format(device=device))
        cmdlist = ['-s', device, 'pull', src, dst]
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist=cmdlist, timeout=timeout)
        if reason == stderr: # Pull complete
            if u'bytes in' in stderr or u'0 files skipped' in stderr:
                ret = True
                reason = u''
            else:
                ret = False
            if u'Permission denied' in stderr:
                reason = PERMISSION_DENY
                self.logger.error("pull: Permission denied")
            elif u'does not exist' in stderr or u'No such file or directory' in stderr:
                reason = NOFILEORFOLDER
                self.logger.error("pull: {}".format(NOFILEORFOLDER))
                self.logger.warning("Sometimes this causes by no permission")
            elif u'0 files pulled' in stderr:
                reason = u'0 files pulled'
                self.logger.warning("pull: 0 files pulled")
            elif reason == DEVICE_OFFLINE:
                self.logger.error("push: {}".format(DEVICE_OFFLINE))
            else:
                if not ret:
                    reason = u'Unknown error'
                    self.logger.error("pull: Unknown error")
                    self.logger.error("stdout: {!r}".format(stdout))
                    self.logger.error("stderr: {!r}".format(stderr))
            if ret:
                # Pull folder
                if u'files pulled' in stderr:
                    pull_pattern = re.compile(r'pull: .* -> (.*)')
                    filelist = pull_pattern.findall(stderr)
                    reason = [os.path.abspath(file_path) for file_path in filelist]
                    if len(reason) == 0:
                        ret = False
                        reason = u'No file pull, may src is folder without file'
                        self.logger.warning("pull: No file pull, may src is folder without file")
                # Pull file
                else:
                    self.logger.info("pull: success")
                    # dst is folder
                    if os.path.isdir(dst):
                        reason = [os.path.abspath(os.path.join(dst, posixpath.basename(src)))]
                    # dst not folder
                    else:
                        reason = [os.path.abspath(dst)]
        else: # Other status
            ret = res
        return ret, reason, stdout, stderr

    @_device_checkor
    def remount(self, device=None):
        '''
        Do adb remount (normally it will remount /system to rw)
        remount request root first
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("remount: start")
        self.logger.info("remount: target - {device}".format(device=device))
        cmdlist = ['-s', device, 'remount']
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        if u'Operation not permitted' in stdout \
           or u'Not running as root' in stdout \
           or u'Permission denied' in stdout:
            self.logger.error("remount: fail - {device}".format(device=device))
            self.logger.warning("remount: maybe need root first")
            return False, PERMISSION_DENY, stdout, stderr
        elif u'remount failed' in stdout:
            self.logger.error("remount: other error - {device}".format(device=device))
            return False, u"remount failed", stdout, stderr
        elif stdout == u'' or u'remount succeeded' in stdout:
            self.logger.info("remount: success")
            return True, u"", stdout, stderr
        else:
            reason = u'Unknown status'
            self.logger.error("remount: unknown status - {device}".format(device=device))
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, reason, stdout, stderr

    @_device_checkor
    def root(self, device=None):
        '''
        Do adb root (normally it will restart adbd on device, need reconnect for ip/auto reconnect for USB)
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("root: start")
        self.logger.info("root: target - {device}".format(device=device))
        cmdlist = ['-s', device, 'root']
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        elif u'adbd cannot run as root in production builds' in stdout:
            self.logger.error("root: Production Builds not support root - {device}".format(device=device))
            return False, u"production builds not support root", stdout, stderr
        elif stdout == u'restarting adbd as root' or stdout == u'':
            self.logger.info("root: success")
            return True, u"", stdout, stderr
        elif u'adbd is already running as root' in stdout:
            self.logger.warning("root: already running as root")
            return True, u"", stdout, stderr
        else:
            reason = u'Unknown status'
            self.logger.error("root: unknown status - {device}".format(device=device))
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, reason, stdout, stderr

    @_device_checkor
    def unroot(self, device=None):
        '''
        Do adb unroot (normally it will restart adbd on device, need reconnect for ip/auto reconnect for USB)
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        Note: Windows adb has unroot, but not in Linux adb ## TODO
        '''
        self.logger.info("unroot: start")
        self.logger.info("unroot: target - {device}".format(device=device))
        cmdlist = ['-s', device, 'unroot']
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        elif u'error' in stdout:
            self.logger.error("unroot: error - {device}".format(device=device))
            self.logger.error("Maybe your target is not userdebug build")
            return False, u"error", stdout, stderr
        elif u'restarting adbd as non root' in stdout or stdout == '':
            self.logger.info("unroot: success")
            return True, u"", stdout, stderr
        elif u'adbd not running as root' in stdout:
            self.logger.warning("unroot: already in unroot")
            return True, u"", stdout, stderr
        else:
            reason = u'Unknown status'
            self.logger.error("unroot: unknown status - {device}".format(device=device))
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, reason, stdout, stderr

    @_device_checkor
    def reboot(self, mode=None, device=None):
        '''
        Do adb reboot (Normal|bootloader|recovery|sideload|fastboot)
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               mode [None(for normal reboot) / bootloader / recovery /
                     sideload(require root) / sideload-auto-reboot / fastboot]
        Output: Result(bool)  Because reboot will hand at adb process, will always treat it success
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("reboot: start")
        if mode is None:
            _mode = u'normal'
            cmdlist = ['-s', device, 'reboot']
        else:
            _mode = _to_unicode(mode)
            cmdlist = ['-s', device, 'reboot', _mode]
        self.logger.info("reboot {mode}: target - {device}".format(mode=_mode, device=device))
        res, p = self._adbcommand_unblocking(cmdlist)
        time.sleep(1)
        if res:
            with ignored(OSError):
                p.kill()
            stdout, stderr = (std.decode(ADB_ENC) for std in p.communicate())
        else:
            stdout, stderr = u'', u''
        if u'\'adb root\' is required for \'adb reboot sideload\'.' in stdout:
            return False, PERMISSION_DENY, stdout, stderr
        elif DEVICE_OFFLINE in stderr:
            self.logger.error("reboot: {}".format(DEVICE_OFFLINE))
            return False, DEVICE_OFFLINE, stdout, stderr
        else:
            self.logger.warning("reboot: always treat as success")
            return True, u'', stdout, stderr

    def reboot_bootloader(self, device=None):
        return self.reboot(mode=u'bootloader', device=device)

    @_device_checkor
    def shell(self, cmd, device=None, timeout=None):
        '''
        Do adb shell with autoexit command
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               cmd (str)
               timeout [int/float/None(infinite)]
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("shell(block): start")
        self.logger.info("shell(block): target - {device}".format(device=device))
        if is_py2:
            cmdlist = ['-s', device, 'shell'] + ['"{}"'.format(_to_utf8(cmd))]
        elif is_py3:
            cmdlist = ['-s', device, 'shell'] + ['"{}"'.format(_to_unicode(cmd))]
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist, timeout=timeout)
        if res is True:
            self.logger.info("shell(block): success")
        else:
            self.logger.warning("shell(block): fail")
        return res, reason, stdout, stderr

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
        self.logger.info("shell: target - {device}".format(device=device))
        if is_py2:
            cmdlist = ['-s', device, 'shell'] + ['"{}"'.format(_to_utf8(cmd))]
        elif is_py3:
            cmdlist = ['-s', device, 'shell'] + ['"{}"'.format(_to_unicode(cmd))]
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
               permission [-g: grant all runtime permissions](bool) ## TODO: Linux adb don't support
               timeout (int/float)
               device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        Note: Some Android System need press OK for verify application
              Sugguest close this option in Android System first before use adb install
              Or you need ignore this function return and wait timeout
        '''
        self.logger.info("install: start")
        self.logger.info("install: target - {device}".format(device=device))
        self.logger.info("apk: {}".format(os.path.abspath(apkfile)))
        cmdlist = ['-s', device, 'install']
        if forward: cmdlist.append('-l')
        if replace: cmdlist.append('-r')
        if test: cmdlist.append('-t')
        if sdcard: cmdlist.append('-s')
        if downgrade: cmdlist.append('-d')
        if permission: cmdlist.append('-g')
        cmdlist.append(os.path.abspath(apkfile))
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist, timeout=timeout)
        if u'Success' in stdout:
            self.logger.info("install: success")
            return True, "", stdout, stderr
        elif reason == TIMEOUT:
            self.logger.error("install: timeout")
            return res, reason, stdout, stderr
        elif u'failed to copy' in stderr:
            reason = stderr
            self.logger.error("install: {!r}".format(reason))
            return res, reason, stdout, stderr
        elif u'Failure' in stdout:
            reason = stdout[stdout.find("Failure"):]
            self.logger.error("install: {!r}".format(reason))
            return res, reason, stdout, stderr
        else:
            reason = u'Unknown status'
            self.logger.error("install: unknown status - {device}".format(device=device))
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, reason, stdout, stderr

    @_device_checkor
    def uninstall(self, package, keepdata=False,
                  timeout=FILE_TRANSFORM_TIMEOUT, device=None):
        '''
        Do adb uninstall
        Input: package [Application package name](str)
               keepdata: [-k: keep data and cache](bool)
               device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("uninstall: start")
        self.logger.info("uninstall: target - {device}".format(device=device))
        self.logger.info("package: {}".format(package))
        cmdlist = ['-s', device, 'uninstall']
        if keepdata: cmdlist.append('-k')
        cmdlist.append(package)
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist, timeout=timeout)
        if u'Success' in stdout:
            self.logger.info("uninstall: success")
            return True, "", stdout, stderr
        elif u'Failure' in stdout:
            self.logger.info("uninstall: {}".format(stdout))
            reason = stdout
            return False, reason, stdout, stderr
        elif reason == TIMEOUT:
            self.logger.info("uninstall: timeout")
            return res, reason, stdout, stderr
        else:
            reason = u'Unknown status'
            self.logger.error("uninstall: unknown status - {device}".format(device=device))
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, reason, stdout, stderr

    def wait_for_device(self, timeout=None):
        '''
        Do adb wait-for-device, blocking untill timeout
        Input: timeout (int/float/None)
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("wait-for-device")
        cmdlist = ['wait-for-device']
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist, timeout=timeout)
        if reason == TIMEOUT:
            self.logger.warning("wait-for-device: timeout")
            return False, TIMEOUT, stdout, stderr
        elif stdout == '' and stderr == '':
            self.logger.info("wait-for-device: success")
            reason = ''
            return True, reason, stdout, stderr
        else:
            reason = u'Unknown status'
            self.logger.error("wait-for-device: unknown status")
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, reason, stdout, stderr

    @_device_checkor
    def disable_verity(self, device=None):
        '''
        Do adb disable-verity (Need root first)
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("disable-verity: start")
        self.logger.info("disable-verity: target - {device}".format(device=device))
        cmdlist = ['-s', device, 'disable-verity']
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        elif u'disable-verity only works for userdebug builds' in stdout:
            self.logger.error("disable-verity: disable-verity only works for userdebug builds - {}".format(device))
            return False, u"disable-verity only works for userdebug builds", stdout, stderr
        elif u'Failed to open' in stdout:
            self.logger.error("disable-verity: Fail to open, Maybe non-root?")
            return False, PERMISSION_DENY, stdout, stderr
        elif stdout == u'' or u'Verity disabled on' in stdout:
            self.logger.info("disable-verity: success")
            return True, u"", stdout, stderr
        elif u'Verity already disabled' in stdout:
            self.logger.warning("disable-verity: already disabled")
            return True, u"", stdout, stderr
        else:
            reason = u'Unknown status'
            self.logger.error("disable-verity: unknown status - {device}".format(device=device))
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, reason, stdout, stderr

    @_device_checkor
    def enable_verity(self, device=None):
        '''
        Do adb enable-verity, if success, need reboot to take effect
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        Note: Linux adb don't support enable_verity ## TODO
        '''
        self.logger.info("enable-verity: start")
        self.logger.info("enable-verity: target - {device}".format(device=device))
        cmdlist = ['-s', device, 'enable-verity']
        res, reason, stdout, stderr = self._adbcommand_blocking(cmdlist)
        if not res:
            self.logger.error(reason)
            return False, reason, stdout, stderr
        elif u'error' in stdout:
            self.logger.error("enable-verity: error - {device}".format(device=device))
            self.logger.error("Maybe your target is not userdebug build")
            return False, u"error", stdout, stderr
        elif u'Failed to open' in stdout:
            self.logger.error("enable-verity: Fail to open, Maybe non-root?")
            return False, PERMISSION_DENY, stdout, stderr
        elif u'Verity enabled on' in stdout  or stdout == '':
            self.logger.info("enable-verity: success")
            return True, u"", stdout, stderr
        else:
            reason = u'Unknown status'
            self.logger.error("enable-verity: unknown status - {device}".format(device=device))
            self.logger.error("stdout: {!r}".format(stdout))
            self.logger.error("stderr: {!r}".format(stderr))
            return False, reason, stdout, stderr

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
        self.logger.info("logcat: target - {device}".format(device=device))
        if params is None:
            cmdlist = ['logcat']
        else:
            cmdlist = ['logcat'] + shlex.split(params)
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
            return True, AdbLogcat(res[1], filehandler, self.logger)

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
        self.logger.info("shell2file: target - {device}".format(device=device))
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
            return True, AdbLogcat(res[1], filehandler, self.logger)
