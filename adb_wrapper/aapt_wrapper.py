# -*- coding: utf-8 -*-
import re

from .base_wrapper import BaseWrapper
from .base_wrapper import BaseWrapperException
from .base_wrapper import SubprocessException
from .base_wrapper import NoBinaryException

class AaptException(BaseWrapperException):
    pass

class AaptFailException(SubprocessException, AaptException):
    def __init__(self, msg, stdout=None, stderr=None):
        super(AaptFailException, self).__init__(msg, stdout, stderr)
        self.msg, self.stdout, self.stderr = msg, stdout, stderr

class NoAaptBinaryException(NoBinaryException):
    pass

class AaptWrapper(BaseWrapper):
    '''
    This is a Google Android aapt wrapper (aapt.exe/aapt).
    It can offer basic get package information / edit package
    Support both Windows/Ubuntu Python2/Python3
    Note: All input cmd should be str(Encoding should be ADB_ENC) or Unicode

    function: dump
    '''
    thirdbinary_p = ()
    _binaryname = u'aapt'
    aapt_error_prefix = 'ERROR: '

    def __init__(self, aapt_file=None, logger=None):
        try:
            super(AaptWrapper, self).__init__(aapt_file, logger)
        except NoBinaryException:
            raise NoAaptBinaryException
        self.logger.info("AaptWrapper: init complete")

    def _set_binary_version(self):
        '''
        Get aapt tool version
        Output: Result [True/False]
                Version [Result==True](str) / Reason(str)
                stdout/stderr
        '''
        self.logger.info("aapt_version: Start")
        cmdlist = ['version']
        stdout, stderr = self._command_blocking(cmdlist)
        pair = re.search(r'Android Asset Packaging Tool, v([0-9.]{1,10})', stdout)
        if pair:
            self.logger.info("aapt version: {}".format(pair.group(1)))
            self._binary_version = pair.group(1)
            if self._binary_version != '0.2':
                self.logger.warning("This script is for 0.2, not sure work or not on other version")
        else:
            self.logger.error("Fail to find aapt version pattern")
            self.logger.error("stdout: %r", stdout)
            self.logger.error("stderr: %r", stderr)

    def dump(self, value, inputfile):
        '''
        Do aapt dump
        Input: value [bading/permissions](str), others to be support if necessary
               inputfile [apkfile](str)
        Output: dict
        If value == badging: Reason will be a dict as below if find target item
                if not there will be no related key:
                {'package': {'name': XXX, 'versionCode': XXX(str), 'versionName': XXX(str)},
                 'sdkVersion: XXX(str),
                 'targetSdkVersion': XXX(str),
                 'application-label': XXX,
                 'uses-permission': [XXX, XXX],
                 'uses-feature': [XXX, XXX],
                 'launchable-activity': {'name': XXX, 'label': XXX, 'icon': XXX},
                 'supports-screens': [XXX, XXX],
                 'densities': [XXX, XXX],
                 'supports-any-density': True/False,
                 'native-code': [XXX, XXX]
                 }
        if value == permissions:
                {'uses-permission': [XXX, XXX],
                 'permission': [XXX, XXX],}
        '''
        cmdlist = ['dump', value, inputfile]
        self.logger.info('dump: %s %s', value, inputfile)
        stdout, stderr = self._command_blocking(cmdlist=cmdlist)
        res_dict = {}
        if self.aapt_error_prefix in stderr:
            reason = stderr[stderr.find(self.aapt_error_prefix)+len(self.aapt_error_prefix):]
            self.logger.error("dump ERROR: %s", reason)
            raise AaptFailException(reason, stdout, stderr)
        if value == u'badging':
            lines = stdout.split(u'\n')
            for line in lines:
                try:
                    key, _value = line.split(u':', 1)
                    value = _value.strip()
                    if key in (u'package', u'launchable-activity', u'application'):
                        items = re.findall(r'(\w+)=\'([\w\.]*)\'', value)
                        package_dict = {subkey: subvalue for subkey, subvalue in items}
                        res_dict.update({key: package_dict})
                        for subkey in package_dict:
                            self.logger.info("%s: %s=%s", key, subkey, package_dict[subkey])
                    elif key in (u'sdkVersion', u'targetSdkVersion', u'application-label'):
                        res_dict.update({key: value.strip(u'\'')})
                        self.logger.info("%s: %s", key, value.strip(u'\''))
                    elif u'application-label-' in key:
                        res_dict.update({key: value.strip(u'\'')})
                        self.logger.info("%s: %s", key, value.strip(u'\''))
                    elif key in (u'uses-permission', u'uses-feature'):
                        if key in res_dict:
                            res_dict[key].append(value.strip(u'\'').replace(u'name=\'', u''))
                        else:
                            res_dict.update({key: [value.strip(u'\'')]})
                        self.logger.info("%s: %s", key, value.strip(u'\'').replace(u'name=\'', u''))
                    elif key in (u'supports-screens', u'densities', u'native-code', u'locales'):
                        value_list = [subvalue.strip('\'') for subvalue in value.split(u'\' \'')]
                        res_dict.update({key: value_list})
                        self.logger.info("%s: %s", key, u'/'.join(value_list))
                    elif key == u'supports-any-density':
                        if u'false' in value:
                            res_dict.update({key: False})
                            self.logger.info("%s: False", key)
                        elif u'true' in value:
                            res_dict.update({key: True})
                            self.logger.info("%s: True", key)
                        else:
                            self.logger.error("Unknown supports-any-density status: %s", value.strip(u'\''))
                    else:
                        self.logger.debug("TODO Item, if need, will add it future: %s", line)
                except ValueError:
                    self.logger.debug("TODO Item, if need, will add it future: %s", line)
        elif value == u'permissions':
            lines = stdout.split(u'\n')
            for line in lines:
                key, _value = line.split(u':', 1)
                value = _value.strip()
                if key in (u'uses-permission', u'permission'):
                    if key in res_dict:
                        res_dict[key].append(value.strip(u'\''))
                    else:
                        res_dict.update({key: [value.strip(u'\'')]})
                    self.logger.info("%s: %s", key, value.strip(u'\''))
                elif key == u'package':
                    pass  # Skip package line on permissions
                else:
                    self.logger.debug("TODO Item, if need, will add it future: %s", line)
        else:
            raise NotImplementedError
        return res_dict
