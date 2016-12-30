# -*- coding: utf-8 -*-
from datetime import datetime
import re

from .adb_wrapper import AdbWrapper
from .adb_wrapper import ADB_SERVER_PORT
from .adb_wrapper import FILE_TRANSFORM_TIMEOUT
from .adb_wrapper import BUGREPORT_TIMEOUT
from .adb_wrapper import NOFILEORFOLDER, PERMISSION_DENY, READONLY, SHELL_FAILED
from .adb_wrapper import AdbFailException

class AdbAuto(AdbWrapper):

    file_property_re = p = re.compile(r'([-lspbcdrwx]{10}) *(\S*) *(\S*) *(\d{0,10}) *(\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{1,2}) *(.*)')
    netcfg_re = re.compile(r'(.*?) *(UP|DOWN) *(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/\d* *0x\d* (([0-9a-fA-F]{2}[:]){5}[0-9a-fA-F]{2})')
    ifconfig_re = re.compile(r'(.*?)\s*Link encap:(.*?)\s*?(HWaddr ([0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}))?\n\s*(inet addr:(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}))?')
    # Android L ps command:user  pid   ppid   vsize  rss    wchan  pc     state codes      name
    android_ps_re = re.compile(r'(\w+) +(\d+) *(\d+) +(\d+) +(\d+) *(.*?) +(\w*) +(D|R|S|T|W|X|Z) +(.*)')
    # BusyBox ps command:pid    userid time      command
    busybox_ps_re = re.compile(r'(\d+) +(\d+) +(\d+:\d+) +(.*)')

    def __init__(self, adb_file=None, logger=None, adb_server_port=ADB_SERVER_PORT):
        super(AdbAuto, self).__init__(adb_file, logger)

    def check_connection(self, device=None):
        '''
        Use adb shell exit to check real connection status
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result [Connection True(True)/Other Status(False)](bool)
                Reason [For Result==False](str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("check_connection: start")
        try:
            stdout, stderr = self.shell(cmd="exit", device=device)
        except AdbFailException as err:
            res = False
            self.logger.error("adb connect error: ", err.msg)
        else:
            if stdout != u"" or stderr != u"":
                res = False
                self.logger.info("adb connection: False")
            else:
                res = True
                self.logger.info("adb connection: True")
            self.logger.info("check_connection: success")
        return res

    def connect_auto(self, device=None, retry_times=3):
        '''
        Before connect, auto check exist connect from adb devices
        If already in connect
            *. If in connect with wrong status, do disconnect
            *. check connect status.
                1. return True if connect
        do connect
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               retry_times (int)
        Output: Device [SN or IP:Port](str)
        '''
        self.logger.info("connect_auto: start")
        try:
            # Check Devices List First
            devices = self.devices()
            for exist_device in devices:
                if device in exist_device:
                    device_name = exist_device  # Because Input Device may be IP only, translate it to SN
                    self.logger.info("connect_auto: Device in adb devices - {}".format(device_name))
                    if devices[device_name] != u'device':
                        self.logger.error("connect_auto: Device status - {}".format(devices[device_name]))
                        self.logger.error("connect_auto: Try to disconnect it")
                        self.disconnect(device_name)
                    else:
                        if self.check_connection(device=device_name):
                            self.logger.info("connect_auto: already connected")
                            return device_name
                    break
        except AdbFailException:
            pass
        # Device not in Devices List or Connection status False, try do adb connect
        for num in range(retry_times):
            try:
                device_name = self.connect(device)
                self.logger.info("connect_auto: connect success")
                if self.check_connection(device=device_name):
                    self.logger.info("connect_auto: check connect Pass")
                    return device_name
                else:
                    self.logger.error("connect_auto: check connect Fail")
                break
            except AdbFailException:
                if num == retry_times - 1:
                    self.logger.info("connect_auto: connect keep fail in {} times".format(retry_times))
                    raise

    def disconnect_auto(self, device=None):
        '''
        Nothing can be do for more auto, just do disconnect directly
        Add this function here just for more orderly
        '''
        return self.disconnect(device=device)

    def shell_auto(self, cmd, device=None, timeout=None):
        '''
        Do adb connect auto then do shell cmd
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               cmd [list or string]
               timeout [int/float/None(infinite)]
        Output: stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("shell_auto: start")
        try:
            devicename = self.connect_auto(device=device)
            stdout, stderr = self.shell(cmd=cmd, device=devicename, timeout=timeout)
            self.logger.info("shell_auto: complete")
        except AdbFailException:
            raise
        return stdout, stderr

    def is_root(self, device=None):
        '''
        Use adb shell id to get adb connect permission
        Do connect_auto first, then shell id
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
        '''
        self.logger.info("is_root: start")
        try:
            stdout, stderr = self.shell_auto(cmd='id', device=device)
        except AdbFailException:
            raise
        if u'uid=0(root)' in stdout:
            self.logger.info("is_root: Now adb {} is root".format(device))
            return True
        elif u'uid=' in stdout:
            self.logger.info("is_root: Now adb {0} is not root - {1}".format(device, stdout))
            return False
        else:
            self.logger.error("is_root: Fail to get response from shell id")
            raise AdbFailException(u"Invalid response from id", stdout, stderr)

    def root_auto(self, device=None):
        '''
        If is_root?
            if not, do root
                    then connect_auto
        If not request to reconnect after root, please use root instead of root_auto
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("root_auto: start")
        try:
            is_root = self.is_root(device=device)
            if is_root:
                self.logger.info("root_auto: Already Root")
                return
        except AdbFailException:
            pass
        try:
            devicename = self.connect_auto(device=device)
            self.root(devicename)
            self.logger.info("root_auto: Root success")
            devicename = self.connect_auto(device=device)
            self.logger.info("root_auto: Re-connect success")
        except AdbFailException:
            raise

    def unroot_auto(self, device=None):
        '''
        If is_root?
            if yes, do unroot
                    then connect
        If not request to reconnect after unroot, please use unroot instead of unroot_auto
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("unroot_auto: start")
        try:
            is_root = self.is_root(device=device)
            if not is_root:
                self.logger.info("unroot_auto: Already unroot")
                return
        except AdbFailException:
            pass
        try:
            devicename = self.connect_auto(device=device)
            self.unroot(devicename)
            self.logger.info("unroot_auto: unroot success")
            devicename = self.connect_auto(device=device)
            self.logger.info("unroot_auto: Re-connect success")
        except AdbFailException:
            raise

    def remount_auto(self, device=None):
        '''
        Use adb remount
        Do connect_auto first, then remount
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("remount_auto: start")
        try:
            devicename = self.connect_auto(device=device)
            self.root_auto(device=device)
            self.remount(device=devicename)
            self.logger.info("remount_auto: success")
        except AdbFailException:
            raise

    def remount_others_auto(self, target, options, device=None):
        '''
        Use adb shell mount to do remount target parition with params
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               target [parition like /factory](str)
               options [like rw/ro/... (No Space!)](str)
        Output: Result(bool)
                Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("remount_others_auto: start")
        try:
            self.root_auto(device=device)
            stdout, stderr = self.shell_auto(cmd='mount -o {0},remount {1}'.format(options, target), device=device)
        except AdbFailException:
            raise
        if stdout == u'':
            self.logger.info("remount_others_auto: success")
        else:
            self.logger.error("remount_others_auto: fail in shell")
            error = stdout
            raise AdbFailException(error, stdout, stderr)

    def push_auto(self, src, dst, device=None, timeout=FILE_TRANSFORM_TIMEOUT):
        '''
        Try adb connect first, then push
        if push fail, try root, then push again
        if push fail, try remoount, then push again
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               src/dst[can be file/folder absolute/relative path](str)
               timeout(int/float)
               Support all adb push support method
        Output: None
        User should know file path after push
        From push command, cannot judgement dst is folder or file
        '''
        self.logger.info("push_auto: start")
        devicename = self.connect_auto(device=device)
        root_try_flag = False
        remount_try_flag = False
        while 1:
            try:
                self.push(src=src, dst=dst, device=devicename, timeout=timeout)
                self.logger.info("push_auto: success")
                break
            except AdbFailException as err:
                self.logger.error("push_auto: fail")
                if err.msg == PERMISSION_DENY:
                    if not root_try_flag:
                        self.logger.info("push_auto: try root")
                        try:
                            self.root_auto(device=devicename)
                        except AdbFailException:
                            pass
                        root_try_flag = True
                        continue
                elif err.msg == READONLY:
                    if not remount_try_flag:
                        self.logger.info("push_auto: try remount")
                        try:
                            self.remount_auto(device=devicename)
                        except AdbFailException:
                            pass
                        remount_try_flag = True
                        continue
                raise
            break

    def pull_auto(self, src, dst, device=None, timeout=FILE_TRANSFORM_TIMEOUT):
        '''
        Try adb connect first, then pull
        if pull fail, try root, then pull again
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               src/dst[can be file/folder absolute/relative path](str)
               timeout(int/float)
               Support all adb pull support method
        Output: filelist
        '''
        self.logger.info("pull_auto: start")
        devicename = self.connect_auto(device=device)
        root_try_flag = False
        while 1:
            try:
                filelist = self.pull(src=src, dst=dst, device=devicename, timeout=timeout)
                self.logger.info("pull_auto: success")
                return filelist
            except AdbFailException as err:
                if err.msg == PERMISSION_DENY:
                    if not root_try_flag:
                        self.logger.info("pull_auto: try root")
                        self.root_auto(device=devicename)
                        root_try_flag = True
                        continue
                raise
            break

    def bugreport_auto(self, filename=None, device=None, timeout=BUGREPORT_TIMEOUT):
        '''
        Try adb connect first, then bugreport
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filename [Write bugreport into file]
        Output: bugreport(bugreport str and filename=None /
                          full filepath filename!=None
        '''
        self.logger.info("bugreport_auto: start")
        devicename = self.connect_auto(device=device)
        res = self.bugreport(filename=filename, device=devicename, timeout=timeout)
        self.logger.info("bugreport_auto: success")
        return res

    def reboot_auto(self, mode=None, device=None):
        '''
        Do adb connect first, then reboot (Normal|bootloader|recovery|sideload|fastboot)
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               mode [None(for normal reboot) / bootloader / recovery /
                     sideload(require root) / sideload-auto-reboot / fastboot]
        Output: None
        '''
        self.logger.info("reboot_auto: start")
        devicename = self.connect_auto(device=device)
        self.reboot(mode=mode, device=devicename)
        self.logger.info("reboot_auto: success")

    def install_auto(self, apkfile, forward=False, replace=False, test=False,
                     sdcard=False, downgrade=False, permission=False,
                     timeout=FILE_TRANSFORM_TIMEOUT, device=None):
        '''
        Do adb connect first, then install
        Input: apkfile [apk file path](str)
               forward: [-l: forward lock application](bool)
               replace [-r: replace existing application](bool)
               test [-t: allow test packages](bool)
               sdcard [-s: install application on sdcard](bool)
               downgrade [-d: allow version code downgrade](bool)
               timeout (int/float)
               device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        Note: Some Android System need press OK for verify application
              Sugguest close this option in Android System first before use adb install
              Or you need ignore this function return and wait timeout
        '''
        self.logger.info("install_auto: start")
        devicename = self.connect_auto(device=device)
        self.install(apkfile=apkfile, forward=forward, replace=replace, test=test,
                     sdcard=sdcard, downgrade=downgrade, permission=permission,
                     timeout=timeout, device=devicename)
        self.logger.info("install_auto: success")

    def uninstall_auto(self, package, keepdata=False,
                       timeout=FILE_TRANSFORM_TIMEOUT, device=None):
        '''
        Do adb connect first, then uninstall
        Input: package [Application package name](str)
               keepdata: [-k: keep data and cache](bool)
               device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("uninstall_auto: start")
        devicename = self.connect_auto(device=device)
        self.uninstall(package, keepdata=keepdata, timeout=timeout, device=devicename)
        self.logger.info("uninstall_auto: success")

    def disable_verity_auto(self, device=None):
        '''
        Do adb connect auto first, then disable-verity
        If fail, try root, then disable-verity again
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("disable_verity_auto: start")
        devicename = self.connect_auto(device=device)
        root_try_flag = False
        while 1:
            try:
                self.disable_verity(device=devicename)
                self.logger.info("disable_verity_auto: success")
                break
            except AdbFailException as err:
                if err.msg == PERMISSION_DENY:
                    if not root_try_flag:
                        self.logger.info("disable_verity_auto: try root")
                        self.root_auto(device=devicename)
                        root_try_flag = True
                        continue
                raise
            break

    def enable_verity_auto(self, device=None):
        '''
        Do adb connect auto first, then enable-verity
        If fail, try root, then enable-verity again
        if success, need reboot to take effect
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        '''
        self.logger.info("enable_verity_auto: start")
        devicename = self.connect_auto(device=device)
        root_try_flag = False
        while 1:
            try:
                self.enable_verity(device=devicename)
                self.logger.info("enable_verity_auto: success")
                break
            except AdbFailException as err:
                if err.msg == PERMISSION_DENY:
                    if not root_try_flag:
                        self.logger.info("enable_verity_auto: try root")
                        self.root_auto(device=devicename)
                        root_try_flag = True
                        continue
                raise
            break

    def logcat_auto(self, filename, params=None, device=None):
        '''
        Do adb connect auto first, then logcat, save stdout to filename
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filename [Full file path](str)
               params [logcat's params, see logcat --help, but don't use -f](str)
        Output: Result(bool)
                Reason(str[Result == False]) / AdbLogcat[Result == True]
        '''
        self.logger.info("logcat_auto: start")
        devicename = self.connect_auto(device=device)
        res, result = self.logcat(filename=filename, params=params, device=devicename)
        if res:
            self.logger.info("logcat_auto: success")
        else:
            self.logger.error("logcat_auto: fail")
        return res, result

    def shell2file_auto(self, filename, cmd, device=None):
        '''
        Do adb connect first, then shell cmd, save stdout to filename
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filename [Full file path](str)
               cmd [Any command can run in adb shell such as dmesg/top](str)
        Output: Result(bool)
                Reason(str[Result == False]) / AdbLogcat[Result == True]
        '''
        self.logger.info("shell2file_auto: start")
        devicename = self.connect_auto(device=device)
        res, result = self.shell2file(filename=filename, cmd=cmd, device=devicename)
        if res:
            self.logger.info("shell2file_auto: success")
        else:
            self.logger.error("shell2file_auto: fail")
        return res, result

    def android_sdk_version_get(self, device=None):
        '''
        Use adb shell getprop ro.build.version.sdk
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
                Version[If result==True](int) or Reason(str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("get_android_sdk_version: start")
        stdout = self.shell_auto(cmd='getprop ro.build.version.sdk', device=device)
        version_r = re.search(r'^(\d+)$', stdout)
        if version_r:
            version = version_r.group(1)
            self.logger.info("get_android_sdk_version: {}".format(version))
            return version
        else:
            self.logger.error("get_android_sdk_version: Fail to get version")
            self.logger.error("stdout: %r", stdout)
            raise AdbFailException(SHELL_FAILED, stdout, u'')

    def file_property(self, filepath, timeformat='%Y-%m-%d %H:%M', device=None):
        '''
        Get target filepath property by 'ls -al'
        For folder, filepath cannot endwith /
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filepath [sugguest to Absolute path, folder path is not support](str)
               timeformat [Python datetime.strptime format](str)
        Output: Result(bool)
                file_property_dict(Result=True) / Reason(str)
                stdout[from adb command](str)
                stderr(str)
        file_property_dict: {'permission': 'drwxr-xr-x',
                             'owner':'root', 'group':'root',
                             'size':'5', 'datetime': datetime,
                             'filename': '', linkfile:'',
                             }
        '''
        self.logger.info("file_property: start")
        self.root_auto(device)
        stdout, stderr = self.shell_auto(cmd=u'ls -al \'{}\''.format(filepath), device=device)
        property_list = self.file_property_re.findall(stdout)
        if len(property_list) > 1:
            raise AdbFailException(u"Don't Support Multi files", stdout, stderr)
        elif len(property_list) == 0:
            raise AdbFailException(NOFILEORFOLDER, stdout, stderr)
        permission, owner, group, size, modifytime, filename = property_list[0]
        modifytime = datetime.strptime(modifytime, timeformat)
        if ' -> ' in filename:
            filename, linkfile = filename.split(' -> ', 1)
        else:
            linkfile = None
        return {'permission': permission, 'owner': owner, 'group': group,
                'size': size, 'datetime': modifytime,
                'filename': filename, 'linkfile': linkfile,}

    def file_exist(self, filepath, device=None):
        res = self.file_property(filepath=filepath, device=device)
        if res:
            return True
        else:
            return False

    def file_remove(self, filepath, device=None):
        '''
        Use rm -rf to delete target
        For folder, filepath cannot endwith /
        Check file exist first
        If exist use rm -f file
        Then check file exist again
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filepath [sugguest to Absolute path](str)
        Output: None
        '''
        self.logger.info("file_remove: start")
        try:
            self.root_auto(device)
            if self.file_exist(filepath=filepath, device=device):
                self.logger.info("file_remove: try to delete")
                self.shell_auto(cmd='rm -rf \'{}\''.format(filepath), device=device)
                if not self.file_exist(filepath=filepath, device=device):
                    self.logger.info("file_remove: success")
                    return
        except AdbFailException as err:
            if err.msg == NOFILEORFOLDER:
                self.logger.info("file_remove: file no exist")
                return
            raise

    def file_find(self, filename, device=None, timeout=None):
        '''
        Use find command get filepath list
        For folder, filepath cannot endwith /
        To prevent permission deny, will try to do root first
        Note: There is no "find" in Android L or lower, need push busybox and alias find to system PATH
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filepath [sugguest to Absolute path](str)
               timeout [None for inifite](int)
        Output: Result(bool)
                Filepath List [Result=True](list) / Reason (str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("file_find: start")
        self.root_auto(device)
        stdout, stderr = self.shell_auto('find / -name \'{}\''.format(filename), device=device, timeout=timeout)
        filelist = re.findall(r'^(\.\/.*)$', stdout)
        if len(filelist) < 1:
            self.logger.info("file_find: no target find")
            raise AdbFailException(NOFILEORFOLDER, stdout, stderr)
        else:
            for filepath in filelist:
                self.logger.info("file_find: {}".format(filepath))
            return filelist

    def file_chmod(self, filename, permission, device=None):
        '''
        Use chmod command change file/folder property
        For folder, filepath cannot endwith /
        To prevent permission deny, will try to do root first
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               filepath [sugguest to Absolute path](str)
               permission [number such as 777 or a+w](str)
        Output: Result(bool)
                Reason (str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("file_chmod: start")
        self.root_auto(device)
        stdout, stderr = self.shell_auto('chmod {0} \'{1}\''.format(permission, filename), device=device)
        if stdout == u'':
            self.logger.info("file_chmod: success")
        else:
            self.logger.info("file_chmod: fail - {}".format(stdout))
            raise AdbFailException(SHELL_FAILED, stdout, stderr)

    def file_link(self, target, filename, params=None, device=None):
        '''
        Use ln command link file/folder
        For folder, filepath cannot endwith /
        To prevent permission deny, will try to do root first
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               target [target link file path, sugguest to Absolute path](str)
               filename [new link file path, sugguest to Absolute path](str)
               params [such as -s or -sfnv](str)
        Output: Result(bool)
                Reason (str)
                stdout[from adb command](str)
                stderr(str)
        '''
        self.logger.info("file_link: start")
        self.root_auto(device)
        if params is None:
            _params = ''
        else:
            _params = params
        stdout, stderr = self.shell_auto('ln {0} \'{1}\' \'{2}\''.format(_params, target, filename), device=device)
        if stdout == u'':
            self.logger.info("file_link: success")
        else:
            self.logger.info("file_link: {}".format(stdout))
            raise AdbFailException(SHELL_FAILED, stdout, stderr)

    def file_alias(self, cmd, target, device=None):
        '''
        Use alias command set temp alias
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               target [short command for alias](str)
               cmd [complete command to alias](str)
        Output: None
        '''
        self.logger.info("file_alias: start")
        self.root_auto(device)
        stdout, stderr = self.shell_auto('alias \'{0}\'=\'{1}\''.format(target, cmd), device=device)
        if stdout == u'':
            self.logger.info("file_alias: success")
        else:
            self.logger.info("file_alias: {}".format(stdout))
            raise AdbFailException(SHELL_FAILED, stdout, stderr)

    def folder_create(self, folderpath, device=None):
        '''
        Use mkdir -p command create folder
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               folderpath [sugguest to Absolute path](str)
        Output: None
        '''
        self.logger.info("folder_create: start")
        self.root_auto(device)
        stdout, stderr = self.shell_auto('mkdir -p \'{}\''.format(folderpath), device=device)
        if stdout == u'':
            self.logger.info("folder_create: success")
        else:
            self.logger.info("folder_create: {}".format(stdout))
            raise AdbFailException(SHELL_FAILED, stdout, stderr)

    def busybox_exist(self, device=None):
        '''
        Check system path include busybox and can be executed
        Check method is to run busybox and check whether output contain BusyBox
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Result(bool)
        '''
        self.logger.info("busybox_exist: start")
        self.root_auto(device)
        stdout, stderr = self.shell_auto('busybox', device=device)
        if u'Busybox' in stdout:
            self.logger.info("busybox_exist: success")
            res = True
        elif u'not found' in stdout:
            self.logger.info("busybox_exist: fail to found")
            res = False
        else:
            self.logger.info("busybox_exist: {}".format(stdout))
            raise AdbFailException(SHELL_FAILED, stdout, stderr)
        return res

    def interface_list_get(self, device=None):
        '''
        Try root first, for Android system, only root can get status from ifconfig/netcfg
        Check Android SDK version, if lower than 23, use netcfg
                                   else, use ifconfig
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: Interfaces (set)
        Interfaces: ({u'interface': u'eth0',
                      u'ip': u'10.37.132.131',
                      u'mac': u'00:11:22:33:44:55'},
                     {u'interface': u'wlan0',
                      u'ip': u'192.168.1.241',
                      u'mac': u'55:44:33:22:11:00'})
        '''
        self.logger.info("interface_list_get: start")
        self.root_auto(device=device)
        version = self.android_sdk_version_get(device=device)
        if version < 23:
            self.logger.info("interface_list_get: target system Android Version <= 5.0 (SDK 22)")
            interface_re = self.netcfg_re
            cmd = 'netcfg'
            mapping = [0, 2, 3]
        else:
            self.logger.info("interface_list_get: target system Android Version >= 6.0 (SDK 23) or other Linux System")
            interface_re = self.ifconfig_re
            cmd = 'ifconfig'
            mapping = [0, 3, 5]
        stdout, stderr = self.shell_auto(cmd, device=device)
        interface_list = []
        result_re = interface_re.findall(stdout)
        if len(result_re) == 0:
            self.logger.warning("Fail to find any network interface")
            self.logger.warning("stdout: %r", stdout)
            interface_set = ()
        else:
            for single in result_re:
                interface_list.append({u'interface':single[mapping[0]],
                                       u'ip':single[mapping[1]],
                                       u'mac':single[mapping[2]]})
                self.logger.info("Find: %5s|%16s|%s", single[mapping[0]], single[mapping[1]], single[mapping[2]])
            interface_set = set(interface_list)
        self.logger.info("interface_list_get: end")
        return interface_set

    def interface_mapping(self, source, target, source_content, device=None):
        '''
        Return target according source with source content
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               source/target [ip/interface/mac](str)
               source_content [source's content, such as eth0/192.168.1.2](str)
        Output: False / target_content (str)
        '''
        self.logger.info("interface_mapping: start")
        self.logger.info("interface_mapping: source_content - {}".format(source_content))
        assert source in (u'ip', 'interface', 'mac'), u"Invalid source, should be ip/interface/mac"
        assert target in (u'ip', 'interface', 'mac'), u"Invalid target, should be ip/interface/mac"
        interface_list = self.interface_list_get(device=device)
        for interface_dict in interface_list:
            if interface_dict[source] == source_content:
                target_content = interface_dict[target]
                self.logger.info("interface_mapping: Get %s - %s", target, target_content)
                return target_content
        self.logger.info("interface_mapping: Fail to find %s according %s", target, source)
        return False

    def interface_according_ip_get(self, ip, device=None):
        '''
        Return interface according IP
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               ip (str)
        Output: False / Interface (str)
        '''
        return self.interface_mapping(u'ip', u'interface', ip, device=device)

    def interface_according_mac_get(self, mac, device=None):
        '''
        Return interface according mac
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               mac (str)
        Output: False / Interface (str)
        '''
        return self.interface_mapping(u'mac', u'interface', mac, device=device)

    def ip_according_interface_get(self, interface, device=None):
        '''
        Return IP according interface
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               interface (str)
        Output: False / ip (str)
        '''
        return self.interface_mapping(u'interface', u'ip', interface, device=device)

    def ip_according_mac_get(self, mac, device=None):
        '''
        Return IP according mac
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               mac (str)
        Output: False / ip (str)
        '''
        return self.interface_mapping(u'mac', u'ip', mac, device=device)

    def mac_according_interface_get(self, interface, device=None):
        '''
        Return mac according interface
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               interface (str)
        Output: False / mac (str)
        '''
        return self.interface_mapping(u'interface', u'mac', interface, device=device)

    def mac_according_ip_get(self, ip, device=None):
        '''
        Return mac according ip
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               interface (str)
        Output: False / mac (str)
        '''
        return self.interface_mapping(u'ip', u'mac', ip, device=device)

    def get_process_list(self, ps_type=u'Android', device=None):
        '''
        Return process list from ps
        Input: device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
               ps_type [Android/BusyBox] (str)
        Output: process_list (set)
        For Android, run command: ps
        For BusyBox, run command: busybox ps (Please confirm busybox in system PATH)
        Process List = [  #Android ps
                          {u'pid': pid(str),
                           u'user': user(str),
                           u'ppid': ppid(str),
                           u'vsize': vsize(int), # By default, it should be kilobyte
                           u'rss': rss(int), # By default, it should be kilobyte
                           u'wchan': wchan(str),
                           u'pc': pc(str),
                           u'statecode': statecode(str),
                           u'name': name(str)}

                          #BusyBox ps
                          {u'pid': pid(str),
                           u'userid': userid(str),
                           u'time': time(str),
                           u'comamnd': command(str)}
                       ]
        '''
        assert ps_type in (u'Android', u'BusyBox')
        self.logger.info("get_process_list: start")
        if ps_type == u'Android':
            ps_re = self.android_ps_re
            cmd = 'ps'
            param_list = [u'user', u'pid', u'ppid', u'vsize', u'rss', u'wchan', u'pc', u'statecode', u'name']
        else:
            if self.busybox_exist(device=device):
                raise AdbFailException(u'No Busybox Found', None, None)
            ps_re = self.busybox_ps_re
            cmd = 'busybox ps'
            param_list = [u'pid', u'userid', u'time', u'command']
        stdout, stderr = self.shell_auto(cmd, device=device)
        result_re = ps_re.findall(stdout)
        if len(result_re) < 1:
            self.logger.error("get_process_list: no process find, abnormal")
            raise AdbFailException(u'no process find', stdout, stderr)
        else:
            processes_list = []
            for process_list in result_re:
                processes_list.append(dict(zip(param_list, process_list)))
            self.logger.info("get_process_list: success")
            return set(processes_list)

    def is_partition_status(self):
        pass

    def usb_mount_exist(self):
        pass

    def ping_status(self):
        pass
