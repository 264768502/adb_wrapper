# -*- coding: utf-8 -*-
import sys
import locale
import subprocess
import shlex
import os
import re
import time
import logging
from io import open
from threading import Thread, Event
import ctypes
from functools import wraps

_VER = sys.version_info
IS_PY2 = (_VER[0] == 2)
# IS_PY3 = (_VER[0] == 3)

if IS_PY2:
    from distutils.spawn import find_executable as find_executable
    from Queue import Queue, Empty
    from contextlib import contextmanager

    @contextmanager
    def ignored(*exceptions):
        try:
            yield
        except exceptions:
            pass

    FILE_TYPES = file

else:
    from shutil import which as find_executable
    from queue import Queue, Empty
    try:
        from contextlib import suppress as ignored
    except ImportError:
        from contextlib import ignored
    from io import IOBase
    FILE_TYPES = IOBase

BINARY_ENC = 'UTF-8'  # Default adb command encode format
BINARY_ENV = os.environ
BINARY_ENV['PYTHONIOENCODING'] = BINARY_ENC
ON_POSIX = 'posix' in sys.builtin_module_names

BUGREPORT_TIMEOUT = 300  # Default bugreport timeout
COMMON_BLOCKING_TIMEOUT = 30  # Default common blocking command timeout
COMMON_UNBLOCKING_TIMEOUT = 60  # Default common unblocking command timeout
FILE_TRANSFORM_TIMEOUT = 60  # Default pull/push timeout

TIMEOUT = u'Command Timeout'
NOFILEORFOLDER = u'No Such File or Directory'
PERMISSION_DENY = u'Permission Deny'
DEVICE_OFFLINE = u'error: device offline'
DEVICE_NOTFOUND = u'Device not found'
UNKNOWNEXCEPTION = u'Unknown Exception'
READONLY = u'Read Only'
SHELL_FAILED = u'Shell Failed'
OUT_ERROR_HANDLING = 'ignore'  # For Decode Error handling, should be ignore/replace

if IS_PY2:
    OUT_CODING = BINARY_ENC

    def cmdlist2subprocess(cmdlist):
        return [_to_utf8(cmd) for cmd in cmdlist]

    def cmdlist2str_forlogging(cmdlist):
        return ' '.join([cmd.decode(BINARY_ENC) for cmd in cmdlist])

else:
    # Python3 always use system encoding to for subprocess.stdout/stderr
    OUT_CODING = locale.getpreferredencoding()

    def cmdlist2subprocess(cmdlist):
        return [_to_unicode(cmd) for cmd in cmdlist]

    def cmdlist2str_forlogging(cmdlist):
        return ' '.join(cmdlist)


def _to_unicode(string):
    return string.decode(BINARY_ENC) if isinstance(string, bytes) else string


def _to_utf8(string):
    return string if isinstance(string, bytes) else string.encode(BINARY_ENC)


def _enqueue_output(out, queue, stop_event, logger):
    '''
    Continues putting subprocess.PIPE data to queue (convert to Unicode before putting)
    '''
    def decode_line(line):
        try:
            _line = line.decode(OUT_CODING)
        except UnicodeDecodeError:
            # Sometimes string passthrough wrong data from subprocess, ignore it
            _line = line.decode(BINARY_ENC, OUT_ERROR_HANDLING)
            logger.critical("UnicodeDecodeError: %r", line)
        else:
            logger.debug("line: %r", _line)
        return _line
    if IS_PY2:
        lineiter = iter(out.readline, b'')
    else:
        lineiter = out
    while not stop_event.is_set():
        logger.debug("Check Line in lineiter, Event: %s | Queue: %s", stop_event.is_set(), id(queue))
        for line in lineiter:
            queue.put(decode_line(line))
        logger.debug("All Line read from lineiter, Event: %s | Queue: %s", stop_event.is_set(), id(queue))
    logger.debug("Thread Event set, Event: %s | Queue: %r", stop_event.is_set(), id(queue))
    rest = out.read()
    try:
        _rest = rest.decode(OUT_CODING)
    except UnicodeDecodeError:
        _rest = rest.decode(BINARY_ENC, OUT_ERROR_HANDLING)
        logger.critical("UnicodeDecodeError: %r", rest)
    else:
        logger.debug("queue_rest: %r", _rest)
    queue.put(_rest)
    out.close()


def _device_checkor(func):
    '''
    Check params "device" is valid or not
    '''
    @wraps(func)
    def wrapper(*args, **kwargs):
        if IS_PY2:
            code = func.func_code
            func_name = func.func_name
        else:
            code = func.__code__
            func_name = func.__name__
        names = list(code.co_varnames)
        args_l = list(args)
        num = names.index('device')
        try:
            device = args_l[num]
            args_flag = True  # device put in args
        except IndexError:
            device = kwargs.get('device', args[0]._device)
            args_flag = False  # device put in kwargs
        if not device:
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

class BaseWrapperException(Exception):
    pass

class NoBinaryException(BaseWrapperException):
    pass

class InvalidBinaryException(BaseWrapperException):
    pass

class WrongCommandException(BaseWrapperException):
    pass

class SubprocessException(BaseWrapperException):
    def __init__(self, msg, stdout=None, stderr=None):
        super(SubprocessException, self).__init__()
        self.msg, self.stdout, self.stderr = msg, stdout, stderr

class NoDeviceException(BaseWrapperException):
    pass

class BaseWrapper(object):
    '''This is Base Wrapper for Android series command line tools'''
    _binaryname = u''  # Should be defined by subclass
    thirdbinary_p = None  # Should be defined by subclass
    nodevice_re_list = [] # Should be defined by subclass
    stdout_help, stderr_help = u'', u'' # Save stdout/stderr which run binary with no parameter

    def __init__(self, binary_file=None, logger=None):
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger('adb')
            if not self.logger.handlers:
                logging.getLogger().setLevel(logging.DEBUG)
                stream_hdl = logging.StreamHandler()
                stream_hdl.setLevel(logging.INFO)
                stream_hdl.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s [%(funcName)s:%(lineno)d] %(message)s'))
                self.logger.addHandler(stream_hdl)
        self.logger.info("%s: init start", self.__class__)
        self.logger.info("Python: %s", sys.version)
        self.logger.info("Sys Encoding: %s", locale.getpreferredencoding())
        self._binary = None  # Define binary file path
        self._device = None
        self._binary_version = None
        self.subproc_list = []
        if binary_file:
            self.binary_file = binary_file
        else:
            if not self._binary_autoset():
                raise NoBinaryException

    def __del__(self):
        '''
        User should explicit call (del BaseWrapper class) to avoid some abnormal process issue
        '''
        self.logger.info("Kill %s process created by this class", self._binaryname)
        for proc in self.subproc_list:
            if proc.returncode is None:
                self.logger.warning("PID %d is runing, try to kill it", proc.pid)
                with ignored(OSError):
                    proc.kill()
        self.logger.info("All %s process is clean", self._binaryname)

    def _binary_autoset(self):
        '''
        Try to find binary in system
        1. Check exist process list, if exist, set it
        2. Check System PATH
        3. Check Environment ANDROID_HOME
        If find, set it by self.binary_file()
        Output: Result (bool)
        '''
        self.logger.info("%s path auto set: start", self._binaryname)
        binary_path = None
        while 1:
            res = self.get_binaryinprolist()
            if res:
                for pid, proc in res.items():
                    self.logger.info("Find: %5s %s", pid, proc)
                    if binary_path:
                        if binary_path != proc:
                            self.logger.warning("find multi runing %s process", self._binaryname)
                    else:
                        binary_path = proc
                        self.logger.info("find %s in exist process list", self._binaryname)
                break

            res = find_executable(self._binaryname)
            if res:
                binary_path = res
                self.logger.info("find %s in system $PATH", self._binaryname)
                break

            if "ANDROID_HOME" in os.environ:
                filename = '{}.exe'.format(self._binaryname) if sys.platform == 'win32' else self._binaryname
                res = os.path.join(os.environ['ANDROID_HOME'], "platform-tools", filename)
                if os.path.exists(res):
                    binary_path = res
                    self.logger.info("find {0} in $ANDROID_HOME: {1}".format(self._binaryname, binary_path))
                    break
            break

        self.logger.info("%s path auto set: end", self._binaryname)
        if binary_path:
            self.binary_file = binary_path
            return True
        else:
            self.logger.warning("find: fail to find %s in process/PATH/ANDROID_HOME", self._binaryname)
            return False

    def get_binaryfile(self):
        '''
        Return _binary file string
        '''
        self.logger.info("get_binary: %s", self._binary)
        return self._binary

    @property
    def binary_file(self):
        return self.get_binaryfile()

    @binary_file.setter
    def binary_file(self, binary):
        '''
        Set binary_file to self._binary
        '''
        self.logger.info("Set _binary: %s", binary)
        if os.path.isfile(binary):
            if os.path.basename(binary).lower() not in (u'{}'.format(self._binaryname),
                                                        u'{}.exe'.format(self._binaryname)):
                self.logger.critical("binary_file must be name as {0} or {0}.exe".format(self._binaryname))
                raise InvalidBinaryException
            self._binary = _to_unicode(binary)
            self.stdout_help, self.stderr_help = self._command_blocking(None)
            try:
                self._set_binary_version()
            except BaseException:
                return False
            else:
                return True
        else:
            self.logger.error("binary file no exist: %s", binary)
            raise NoBinaryException

    @property
    def binary_version(self):
        return self._binary_version

    def _set_binary_version(self):
        raise NotImplementedError

    def get_binaryinprolist(self):
        '''
        return binary proc_dict
        if fail to find binary, return {}
        if error, return None
        proc_dict = {
                        pid(str): proc(str),
                        ...
                    }
        '''
        self.logger.info("get_binaryinprolist start")
        proc_dict = {}
        if sys.platform == 'win32':
            # Only Support Win7 or newer (Don't support cygwin)
            cmdlist = shlex.split('wmic process get processid,executablepath')
            try:
                self.logger.info("Windows cmd: %s", ' '.join(cmdlist))
                _wmilist = subprocess.check_output(cmdlist)
                wmilist = _to_unicode(_wmilist)
            except subprocess.CalledProcessError:
                self.logger.error("wmic run error, please check manually in host")
                return None
            except WindowsError as err:
                self.logger.error("wmic run exception: {}".format(err))
                self.logger.exception("Stack: ")
                return None
            pattern = re.compile(r'(.*?) *(\d{1,8})')
            for proline in wmilist.split(u'\r\n'):
                _ = pattern.search(proline)
                if not _:
                    continue
                proc, pid = _.groups()
                if os.path.basename(proc).lower() == u'{}.exe'.format(self._binaryname):
                    proc_dict.update({pid: proc})
                for thirdbinary_p in self.thirdbinary_p:
                    if os.path.basename(proc) == thirdbinary_p:
                        self.logger.critical("Find 3rd %s, please uninstall it to prevent unexpected error", self._binaryname)
                        self.logger.critical("3rd %s: %s", self._binaryname, proc)
        elif sys.platform in ('linux2', 'linux'):
            pids = [pid for pid in os.listdir('/proc') if pid.isdigit()]
            for pid in pids:
                try:
                    proc = open(os.path.join('/proc', pid, 'exe'), 'rb').read().decode('UTF-8', OUT_ERROR_HANDLING).strip()
                except IOError:
                    continue
                if os.path.basename(proc) == self._binaryname:
                    proc_dict.update({pid: proc})
        else:
            raise Exception("Don't support your system: {system}".format(system=sys.platform))
        for pid, proc in proc_dict.items():
            self.logger.info("%s process: pid(%s)|proc(%s)", self._binaryname, pid, proc)
        self.logger.info("get_binaryinprolist complete")
        return proc_dict

    def _cmdlist_convert(self, cmdlist):
        if not isinstance(cmdlist, list) and cmdlist:
            _cmdlist = shlex.split(cmdlist)
        elif isinstance(cmdlist, list):
            _cmdlist = cmdlist
        else:
            _cmdlist = []
        _cmdlist.insert(0, self._binary)
        # Both Python2/Python3 request subprocess args as str(but Python2 str is btye, Python3 str is Unicode)
        _cmdlist = cmdlist2subprocess(_cmdlist)
        self.logger.info("%s command: %r", self._binaryname, cmdlist2str_forlogging(_cmdlist))
        return _cmdlist

    def _command_blocking(self, cmdlist, timeout=COMMON_BLOCKING_TIMEOUT):
        '''
        Run command blocking
        Input: cmdlist(list)
               timeout(int/float/None(infinite))
        Output: Result(bool) / Reason(str) / stdout(str) / stderr(str)
        If find stderr != '', Result = False, Reason = stderr
        else, Result = True, Reason = stdout
        Exception, Result = False, Reason = Exception
        Only Push/Pull can ignore stderr, others must check when stderr != ''
        '''
        def stop_queue():
            stdout_stop.set()
            stderr_stop.set()
            with ignored(OSError):
                p.terminate()
            stdout_t.join()
            stderr_t.join()
        _cmdlist = self._cmdlist_convert(cmdlist)
        stdout_str, stderr_str = u'', u''
        start_time = time.time()
        try:
            p = subprocess.Popen(_cmdlist, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 bufsize=1, close_fds=ON_POSIX)
        except (OSError, ValueError) as err:
            self.logger.error("Run %s command Exception", self._binaryname)
            self.logger.error("Exception: %r", err)
            self.logger.exception("Stack: ")
            stderr_str = u"{}".format(err)
            raise SubprocessException(str(err), stdout_str, stderr_str)
        else:
            self.subproc_list.append(p)
            _timeout = 999999999 if timeout is None else timeout
            self.logger.info("%s command timeout: %d", self._binaryname, _timeout)
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
            stderr_list = []
            while p.returncode is None and time.time() - start_time < _timeout:
                # Suppose if too much stdout, there will be no stderr output
                # So check stdout first, once there is no data from stdout, then check stderr
                with ignored(Empty):
                    while time.time() - start_time < _timeout:
                        stdout_tmp = stdout_q.get_nowait()
                        self.logger.debug("stdout_str: %r", stdout_tmp)
                        stdout_list.append(stdout_tmp)
                with ignored(Empty):
                    while time.time() - start_time < _timeout:
                        stderr_tmp = stderr_q.get_nowait()
                        stderr_list.append(stderr_tmp)
                        self.logger.debug("stderr_str: %r", stderr_tmp)
                if stderr_list:
                    stderr_str += ''.join(stderr_list)
                    stderr_list = []
                for nodevice_re in self.nodevice_re_list:
                    if re.search(nodevice_re, stderr_str):
                        with ignored(OSError): p.kill()
                        stop_queue()
                        raise NoDeviceException
                p.poll()
            stop_queue()
            with ignored(Empty):
                while 1:
                    stdout_tmp = stdout_q.get_nowait()
                    stdout_list.append(stdout_tmp)
                    self.logger.debug("stdout_str: %r", stdout_tmp)
            stdout_str = u''.join(stdout_list)
            with ignored(Empty):
                while 1:
                    stderr_tmp = stderr_q.get_nowait()
                    stderr_list.append(stderr_tmp)
                    self.logger.debug("stderr_str: %r", stderr_str)
            stderr_str += u''.join(stderr_list)
            if p.returncode is None:
                p.poll()
                with ignored(OSError): p.kill()
                p.wait()
                raise SubprocessException(TIMEOUT, stdout_str, stderr_str)
            if stdout_str == self.stdout_help and stderr_str == self.stderr_help:
                raise WrongCommandException
        return stdout_str.strip(), stderr_str.strip()

    def kill_binary_proc(self):
        '''
        From System level to kill all binary process(create by this class)
        '''
        self.logger.info("Kill %s process start", self._binaryname)
        if self.subproc_list == []:
            self.logger.info("there is no %s process found", self._binaryname)
            return True
        for process in self.subproc_list:
            self.logger.info("Try to kill %s, PID: %d", self._binaryname, process.pid)
            with ignored(Exception):
                process.kill()
        return True

    def get_device(self):
        '''
        Get instance default device from self._device
        Output: self._device or False
        '''
        if not self._device:
            self.logger.error("device is not set, please set_device first")
        self.logger.info("get_device: %s", self._device)
        return self._device

    @property
    def device(self):
        return self.get_device()

    @device.setter
    def device(self, device):
        '''
        Set default device(str) for binary device command
        device should be SN or IP or IP:PORT
        set device to self._device
        Output: True
        '''
        self._device = _to_unicode(device)
        self.logger.info("set_device: %s", self._device)
        ip_pattern = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
        if ip_pattern.match(self._device):
            self.logger.warning("Device is from network without PORT")
            self.logger.warning("Suggust use device from 'connect' to avoid unknown error")
