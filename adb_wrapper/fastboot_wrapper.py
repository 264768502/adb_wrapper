# -*- coding: utf-8 -*-
import re
import numbers
import inspect

from .base_wrapper import BaseWrapper
from .base_wrapper import _device_checkor
from .base_wrapper import UNKNOWNEXCEPTION
from .base_wrapper import SubprocessException
from .base_wrapper import NoDeviceException

class FastbootFailException(SubprocessException):
    def __init__(self, msg, stdout=None, stderr=None):
        super(FastbootFailException, self).__init__(msg, stdout, stderr)
        self.msg, self.stdout, self.stderr = msg, stdout, stderr

class FastbootWrapper(BaseWrapper):
    '''
    This is a Google Android fastboot wrapper (fastboot.exe/fastboot).
    It can offer basic get package information / edit package
    Support both Windows/Ubuntu Python2/Python3
    Note: All input cmd should be str(Encoding should be ADB_ENC) or Unicode
    '''
    thirdbinary_p = ()
    _binaryname = u'fastboot'
    nodevice_re_list = [u'< waiting for ']
    fastboot_fail_re = re.compile(r'FAILED ([\w\W]*)')
    fastboot_error_re = re.compile(r'error: (.*)')

    def __init__(self, fastboot_file=None, logger=None):
        super(FastbootWrapper, self).__init__(fastboot_file, logger)
        self._common_fastboot_timeout = 10
        self.logger.info("FastbootWrapper: init complete (default timeout: %s)", self._common_fastboot_timeout)

    def _set_binary_version(self):
        '''
        Get fastboot tool version
        Output: None
        '''
        self.logger.info("fastboot_version: Start")
        cmdlist = ['--version']
        stdout, stderr = self._command_blocking(cmdlist)
        pair = re.search(r'fastboot version ([\w\W]+)', stdout)
        if pair:
            self.logger.info("fastboot version: %s", pair.group(1))
            self._binary_version = pair.group(1)
        else:
            self.logger.error("Fail to find fastboot version pattern")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)

    def _error_stderr_check(self, stdout, stderr):
        '''
        Check error pattern, if found raise Exception
        '''
        if re.search(self.fastboot_fail_re, stderr):
            reason = re.search(self.fastboot_fail_re, stderr).group(1).strip()
            self.logger.error("error: %s", reason)
            raise FastbootFailException(reason, stdout, stderr)
        if re.search(self.fastboot_error_re, stderr):
            reason = re.search(self.fastboot_error_re, stderr).group(1).strip()
            self.logger.error("error: %s", reason)
            raise FastbootFailException(reason, stdout, stderr)

    @property
    def common_fastboot_timeout(self):
        '''
        Get common timeout for all fastboot by default, can be float/int
        user can also define timeout by every function seperate
        '''
        return self._common_fastboot_timeout

    @common_fastboot_timeout.setter
    def common_fastboot_timeout(self, value):
        '''
        Set common timeout for all fastboot by default, can be float/int
        user can also define timeout by every function seperate
        '''
        assert isinstance(value, numbers.Real)
        self.logger.info("Set fastboot timeout: %f", value)
        self._common_fastboot_timeout = value

    def devices(self, timeout=None):
        '''
        Get device list from fastboot device, blocking operation
        Output: Device Dict [Maybe blank dict if no device](dict) or Reason(str)
        Device Dict: {
                        Device(IP:Port or SN): Status (device/fastboot/unauthorized/offline),
                        ...
        }
        '''
        self.logger.info("devices: start")
        cmdlist = ['devices']
        device_pattern = re.compile(r'([0-9a-zA-Z_:.-\?]*)\s*(fastboot|no permissions)')
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._command_blocking(cmdlist, timeout=_timeout)
        self._error_stderr_check(stdout, stderr)
        devices = device_pattern.findall(stdout)
        devices_dict = {}
        for device in devices:
            if re.match(r'(tcp|udp):\w+(\:\d+)?', device[0]):
                device_type = u'network'
            elif re.match(r'\?+', device[0]):
                device_type = u'no SN'
            else:
                device_type = u'usb'
            if device[0] == u'of' and device[1] == u'device':
                continue
            self.logger.info("Find %7s device: %s | %s", device_type, device[0], device[1])
            devices_dict.update({device[0]: device[1]})
        return devices_dict

    def _run_fb_cmd(self, cmdlist, timeout):
        '''
        Common method to run fastboot cmd (except devices)
        Input: cmdlist (list)
               timeout (int)
        Output: stdout, stderr
        May raise FastbootFailException
        '''
        try:
            stdout, stderr = self._command_blocking(cmdlist=cmdlist, timeout=timeout)
        except NoDeviceException:
            self.logger.error("No Device to detected")
            raise FastbootFailException(u"No Device to detected")
        self._error_stderr_check(stdout, stderr)
        return stdout, stderr

    @_device_checkor
    def getvar(self, variable, device=None, timeout=None, *args, **kwargs):
        '''
        Get bootloader variable from fastboot getvar, blocking operation
        Input:  variable(str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: variable_result [if variable is all, will return dict {variable: value}
                                 if variable not implemented, will be False
                                 other will be str]
        '''
        self.logger.info("getvar: start")
        self.logger.info("getvar: device - %s / variable - %s", device, variable)
        cmdlist = ['-s', device, 'getvar', variable]
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if variable == u'all':
            va_list = re.findall(r'\(bootloader\) (\w)+: (.+)', stderr)
            va_dict = {key:value for key, value in va_list}
            for val in va_dict:
                self.logger.info("Variable %s: %s", val, va_dict[val])
            return va_dict
        elif re.match(r'{}: (.+)'.format(variable), stderr):
            self.logger.info("Variable %s: %s", variable, re.match(r'{}: (.+)'.format(variable), stderr))
            return re.match(r'{}: (.+)'.format(variable), stderr)
        else:
            self.logger.error("getvar unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def erase(self, partition, device=None, timeout=None, *args, **kwargs):
        '''
        Erase a flash partition by fastboot
        Input:  partition(str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("erase: start")
        self.logger.info("erase: device - %s / partition - %s", device, partition)
        cmdlist = ['-s', device, 'erase', partition]
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'OKAY ' in stderr:
            self.logger.error("erase success")
        else:
            self.logger.error("erase unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def format(self, partition, fs_type=None, size=None, device=None, timeout=None, *args, **kwargs):
        '''
        Erase a flash partition by fastboot
        Input:  partition(str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("format: start")
        self.logger.info("format: device - %s / partition - %s", device, partition)
        if not fs_type:
            _fs_type = fs_type
            self.logger.info("fs_type: %s", fs_type)
        else:
            _fs_type = u''
        if not size:
            _size = size
            self.logger.info("size: %s", size)
        else:
            _size = u''
        cmdlist = ['-s', device, 'format:{}:{}'.format(_fs_type, _size), partition]
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'Formatting is not supported for file system with type' in stderr:
            reason = u'Not supported fs type'
            self.logger.error("format error: %s", reason)
            raise FastbootFailException(reason, stdout, stderr)
        elif u'OKAY ' in stderr:
            self.logger.info('format success')
        else:
            self.logger.error("format unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def reboot(self, target=None, device=None, timeout=None, *args, **kwargs):
        '''
        reboot by fastboot
        Input:  target [None/bootloader](str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("reboot: start")
        self.logger.info("reboot: device - %s / partition - %s", device, target)
        if not target:
            _target = target
        else:
            _target = u''
        self.logger.info("reboot target: %s", target if target else u'normal')
        cmdlist = ['-s', device, 'reboot']
        if target:
            cmdlist.append(target)
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        std = stdout + stderr
        if u'rebooting' in std.lower() and u'finished' in std.lower():
            self.logger.info("reboot: success")
        else:
            self.logger.error("reboot unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def reboot_bootloader(self, device=None, timeout=None, *args, **kwargs):
        '''
        reboot bootloader by fastboot
        Input:  target [None/bootloader](str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.reboot(target='bootloader', device=device, timeout=timeout, *args, **kwargs)

    @_device_checkor
    def continue_(self, device=None, timeout=None, *args, **kwargs):
        # Because continue is key word of Python, so use continue_
        '''
        continue by fastboot
        Input:  device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("continue: start")
        self.logger.info("continue: device - %s", device)
        cmdlist = ['-s', device, 'continue']
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'boot' in stderr and u'finished' in stderr:
            self.logger.info("continue: success")
        else:
            self.logger.error("continue unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def boot(self, kernel, ramdisk=None, second=None, device=None, timeout=None, *args, **kwargs):
        '''
        boot by fastboot
        Input:  kernel (str)
                ramdisk (str)
                second (str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("boot: start")
        cmdlist = ['-s', device, 'boot']
        self.logger.info("continue: device - %s", device)
        while 1:
            self.logger.info("boot: kernel - %s", kernel)
            cmdlist.append(kernel)
            if ramdisk:
                self.logger.info("boot: ramdisk - %s", ramdisk)
                cmdlist.append(ramdisk)
            else:
                break
            if second:
                self.logger.info("boot: second - %s", second)
                cmdlist.append(second)
            break
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'booting' in stderr and u'OKAY' in stderr and u'finished' in stderr:
            self.logger.info("boot: success")
        else:
            self.logger.error("boot unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def flash(self, partition, filename=None, device=None, timeout=None, *args, **kwargs):
        '''
        boot by fastboot
        Input:  partition (str)
                filename (str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("flash: start")
        cmdlist = ['-s', device]
        for key, value in kwargs.items():
            cmdlist.extend([key, value])
        cmdlist.extend(['flash', partition])
        self.logger.info("flash: device - %s", device)
        if filename:
            self.logger.info("flash: filename - %s", filename)
            cmdlist.append(filename)
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'sending' in stderr and u'writing' in stderr and u'OKAY' in stderr:
            self.logger.info("flash: success")
        else:
            self.logger.error("flash unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def flashraw(self, kernel, ramdisk=None, second=None, device=None, timeout=None, *args, **kwargs):
        '''
        flash:raw by fastboot
        Input:  kernel (str)
                ramdisk (str)
                second (str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("flashraw: start")
        cmdlist = ['-s', device, 'flash:raw', 'boot']
        self.logger.info("flashraw: device - %s", device)
        while 1:
            self.logger.info("flashraw: kernel - %s", kernel)
            cmdlist.append(kernel)
            if ramdisk:
                self.logger.info("flashraw: ramdisk - %s", ramdisk)
                cmdlist.append(ramdisk)
            else:
                break
            if second:
                self.logger.info("flashraw: second - %s", second)
                cmdlist.append(second)
            break
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'booting' in stderr and u'OKAY' in stderr and u'finished' in stderr:
            self.logger.info("flashraw: success")
        else:
            self.logger.error("flashraw unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def flashall(self, device=None, timeout=None, reboot=True, *args, **kwargs):
        '''
        flashall by fastboot
        Input:  device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("flashall: start")
        cmdlist = ['-s', device]
        if not reboot:
            cmdlist.append(u'--skip-reboot')
        cmdlist.append(u'flashall')
        self.logger.info("flashall: device - %s", device)
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'OKAY' in stderr and 'finished' in stderr:
            self.logger.info("flashall: success")
        else:
            self.logger.error("flashall unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def update(self, filename, device=None, timeout=None, reboot=True, *args, **kwargs):
        '''
        update by fastboot
        Input:  filename (str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        TODO: support slot/-w
        '''
        self.logger.info("update: start")
        cmdlist = ['-s', device]
        if not reboot:
            cmdlist.append(u'--skip-reboot')
        cmdlist.extend(['update', filename])
        self.logger.info("update: device - %s / file - %s", device, filename)
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'OKAY' in stderr and 'finished' in stderr:
            self.logger.info("update: success")
        else:
            self.logger.error("update unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def set_active(self, slot, device=None, timeout=None, *args, **kwargs):
        '''
        set_active by fastboot
        Input:  slot (str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("set_active: start")
        cmdlist = ['-s', device, 'set_active', slot]
        self.logger.info("set_active: device - %s / slot - %s", device, slot)
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'OKAY' in stderr and 'finished' in stderr:
            self.logger.info("set_active: success")
        else:
            self.logger.error("set_active unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def oem(self, command, device=None, timeout=None, *args, **kwargs):
        '''
        oem by fastboot
        Input:  command (str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("oem: start")
        cmdlist = ['-s', device, 'oem', command]
        self.logger.info("oem: device - %s / command - %s", device, command)
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'OKAY' in stderr and 'finished' in stderr:
            self.logger.info("oem: success")
        else:
            self.logger.error("oem unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def _flashing(self, command, device=None, timeout=None, *args, **kwargs):
        '''
        flashing by fastboot
        Input:  command [lock/unlock/lock_critical/unlock_critical/lock_bootloader](str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        caller = inspect.stack()[1][3]
        self.logger.info("%s: start", caller)
        cmdlist = ['-s', device, 'flashing', command]
        self.logger.info("%s: device - %s", caller, device)
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'OKAY' in stderr and 'finished' in stderr:
            self.logger.info("%s: success", caller)
        else:
            self.logger.error("%s unknown error", caller)
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    @_device_checkor
    def flashing_lock(self, device=None, timeout=None, *args, **kwargs):
        '''
        flashing lock by fastboot
        Input:  device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self._flashing(u'lock', device=device, timeout=timeout, *args, **kwargs)

    @_device_checkor
    def flashing_unlock(self, device=None, timeout=None, *args, **kwargs):
        '''
        flashing unlock by fastboot
        Input:  device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self._flashing(u'unlock', device=device, timeout=timeout, *args, **kwargs)

    @_device_checkor
    def flashing_lock_critical(self, device=None, timeout=None, *args, **kwargs):
        '''
        flashing lock_critical by fastboot
        Input:  device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self._flashing(u'lock_critical', device=device, timeout=timeout, *args, **kwargs)

    @_device_checkor
    def flashing_unlock_critical(self, device=None, timeout=None, *args, **kwargs):
        '''
        flashing unlock_critical by fastboot
        Input:  device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self._flashing(u'unlock_critical', device=device, timeout=timeout, *args, **kwargs)

    @_device_checkor
    def flashing_lock_bootloader(self, device=None, timeout=None, *args, **kwargs):
        '''
        flashing lock_bootloader by fastboot
        Input:  device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self._flashing(u'lock_bootloader', device=device, timeout=timeout, *args, **kwargs)

    @_device_checkor
    def flashing_get_unlock_ability(self, device=None, timeout=None, *args, **kwargs):
        '''
        flashing by fastboot
        Input:  command [lock/unlock/lock_critical/unlock_critical/lock_bootloader](str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: True/False
        '''
        caller = u'flashing_get_unlock_ability'
        self.logger.info("%s: start", caller)
        cmdlist = ['-s', device, 'flashing', 'get_unlock_ability']
        self.logger.info("%s: device - %s", caller, device)
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        abi_re = re.compile(r'get_unlock_ability: (\d)')
        if u'OKAY' in stderr and 'finished' in stderr and abi_re.search(stderr):
            abi = abi_re.search(stderr).group(1)
            self.logger.info("%s: success: %s", caller, abi)
            return bool(abi)
        else:
            self.logger.error("%s unknown error", caller)
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

    def flashing_get_unlock_bootloader_nonce(self, device=None, timeout=None, *args, **kwargs):
        '''
        flashing get_unlock_bootloader_nonce by fastboot
        Input:  command [lock/unlock/lock_critical/unlock_critical/lock_bootloader](str)
                device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: nonce
        TODO: Wait Nexus 9 to verify
        '''
        raise NotImplementedError

    @_device_checkor
    def wipe(self, device=None, timeout=None, *args, **kwargs):
        '''
        -w function in fastboot for wipe userdata/cache
        Input:  device [SN(for USB device) / Protocol:IP:Port(for network device)](str) / None(for self._device)
        Output: None
        '''
        self.logger.info("wipe: start")
        cmdlist = ['-s', device, '-w']
        self.logger.info("wipe: device - %s", device)
        _timeout = timeout if timeout else self._common_fastboot_timeout
        stdout, stderr = self._run_fb_cmd(cmdlist, _timeout)
        if u'OKAY' in stderr and 'finished' in stderr:
            self.logger.info("wipe: success")
        else:
            self.logger.error("wipe unknown error")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)
            raise FastbootFailException(UNKNOWNEXCEPTION, stdout, stderr)

# TODO: -u (for format)
#       --skip-secondary (flashall/update)
