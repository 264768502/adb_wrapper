# -*- coding: utf-8 -*-
import unittest
import time
import sys
import os
import tempfile
import posixpath

sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
from adb_wrapper.adb_wrapper import AdbWrapper
from adb_wrapper.adb_wrapper import AdbFailException, AdbConnectFail
from adb_wrapper.adb_wrapper import ignored

VALID_DUT_IP = '10.37.132.174'
INVALID_DUT_IP = '192.168.1.254'
BOOT_UP_TIME = 30

def multi_connect(adb, device=None, num=5):
    for _ in range(num):
        try:
            if device:
                device_name = adb.connect(device)
            else:
                device_name = adb.connect()
        except AdbConnectFail:
            continue
        else:
            break
    else:
        raise Exception('Adb Connect Fail time over 5')
    return device_name


def root_confirm(adb, device=None):
    try:
        if device:
            adb.root(device)
        else:
            adb.root()
    except AdbFailException:
        if device:
            adb.disconnect(device)
            multi_connect(adb, device)
            adb.root(device)
        else:
            adb.disconnect()
            multi_connect(adb)
            adb.root()

class AdbServerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.adb = AdbWrapper()

    @classmethod
    def tearDownClass(cls):
        del cls.adb

    def test_doublestartserver(self):
        self.adb.start_server()
        self.adb.start_server()

    def test_doublekillserver(self):
        self.adb.kill_server()
        self.adb.kill_server()


class AdbConnectTest(unittest.TestCase):

    valid_dut_ip = VALID_DUT_IP
    invalid_dut_ip = INVALID_DUT_IP
    adb = AdbWrapper()

    @classmethod
    def setUpClass(cls):
        cls.adb = AdbWrapper()

    @classmethod
    def tearDownClass(cls):
        del cls.adb

    def setUp(self):
        self.adb.kill_server()

    def tearDown(self):
        self.adb.device = u''
        self.adb.kill_server()

    def test_connect_invalid(self):
        with self.assertRaises(AdbConnectFail):
            self.adb.connect(self.invalid_dut_ip)
        self.adb.disconnect(self.invalid_dut_ip)

    def test_connect_valid(self):
        device_name = self.adb.connect(self.valid_dut_ip)
        self.assertEqual(device_name, self.valid_dut_ip+':5555')

    def test_connect_default(self):
        self.adb.device = self.valid_dut_ip
        device_name = multi_connect(self.adb)
        res_device = self.adb.devices()
        self.assertTrue(device_name in res_device)
        self.adb.disconnect()

    def test_devices(self):
        device_name = multi_connect(self.adb, self.valid_dut_ip)
        res_device = self.adb.devices()
        self.assertTrue(device_name in res_device)
        self.adb.disconnect(self.valid_dut_ip)
        res_device = self.adb.devices()
        self.assertFalse(res_device)

class AdbrootTest(unittest.TestCase):

    valid_dut_ip = VALID_DUT_IP
    boot_up_time = BOOT_UP_TIME
    adb = AdbWrapper()

    @classmethod
    def setUpClass(cls):
        cls.adb = AdbWrapper()

    @classmethod
    def tearDownClass(cls):
        del cls.adb

    def setUp(self):
        self.adb.disconnect(self.valid_dut_ip)
        self.adb.device = multi_connect(self.adb, self.valid_dut_ip)

    def tearDown(self):
        self.adb.device = u''
        self.adb.kill_server()

    def test_root(self):
        self.adb.root()
        self.adb.disconnect()
        multi_connect(self.adb)
        stdout, _ = self.adb.shell('id')
        self.assertTrue(u'root' in stdout)
        self.adb.unroot()
        self.adb.disconnect()
        multi_connect(self.adb)
        stdout, _ = self.adb.shell('id')
        self.assertTrue(u'shell' in stdout)

    def test_remount(self):
        self.adb.unroot()
        multi_connect(self.adb)
        with self.assertRaises(AdbFailException):
            self.adb.remount()
        root_confirm(self.adb)
        multi_connect(self.adb)
        self.adb.remount()

    def test_verity(self):
        self.adb.unroot()
        multi_connect(self.adb)
        with self.assertRaises(AdbFailException):
            self.adb.disable_verity()
        root_confirm(self.adb)
        multi_connect(self.adb)
        self.adb.disable_verity()
        self.adb.disable_verity()
        self.adb.enable_verity()
        self.adb.enable_verity()
        self.adb.disable_verity()

    def test_reboot(self):
        self.adb.reboot()
        time.sleep(self.boot_up_time)

class AdbFileTest(unittest.TestCase):

    valid_dut_ip = VALID_DUT_IP
    pushfolder_nofileinfolder = os.path.join(tempfile.gettempdir(), 'no_file_in_folder') # No file in folder
    pushfolder_withfileinfolder = os.path.join(tempfile.gettempdir(), 'has_file_in_folder') # With file in folder
    pushfile_success = os.path.join(tempfile.gettempdir(), 'exist_file')
    pushfile_nofile = os.path.join(tempfile.gettempdir(), 'noexist_file') # No such file
    dstfolder_successfolder = '/sdcard/Movies' # Push success
    dstfolder_permissiondeny = '/' # Permission deny
    dstfolder_sdcard = '/sdcard'
    dstfile_successfile = '/sdcard/Movies/test1' # target push dstfile
    pullfile_success = '/system/build.prop' # Pull success with root
    pullfile_permissiondeny = '/system/init.rc' # Permission deny without root
    pullfile_nofile = '/sdcard/no_such_file' # No such file
    pullfolder_success = '/system/boot' # exist folder
    files_in_pullfolder_success = (u'bl_recovery.subimg', u'tzk_recovery.subimg')
    pullfolder_nofolder = '/sdcard/noexist_folder' # No exist folder
    pullremote_srcfile = os.path.join(tempfile.gettempdir(), 'p3')
    pullremote_srcfolder = tempfile.gettempdir()
    apk = os.path.join(os.path.dirname(__file__), 'HelloWorld.apk')
    apk_package = 'com.helloworld.android'
    apk_nopermission = 'com.android.systemui'
    adb = AdbWrapper()

    @classmethod
    def setUpClass(cls):
        cls.adb = AdbWrapper()

    @classmethod
    def tearDownClass(cls):
        del cls.adb

    def setUp(self):
        self.adb.device = multi_connect(self.adb, self.valid_dut_ip)
        self.adb.unroot()
        multi_connect(self.adb)

    def tearDown(self):
        multi_connect(self.adb)
        self.adb.unroot()
        self.adb.device = u''
        self.adb.kill_server()

    def test_apk(self):
        stdout, stderr = self.adb.shell('settings put global package_verifier_include_adb 0')
        self.assertFalse(stdout)
        self.assertFalse(stderr)
        self.adb.install(self.apk)
        self.adb.uninstall(self.apk_package)
        with self.assertRaises(AdbFailException):
            self.adb.uninstall(self.apk_nopermission)
        stdout, stderr = self.adb.shell('settings put global package_verifier_include_adb 1')
        self.assertFalse(stdout)
        self.assertFalse(stderr)

    def test_push(self):
        with ignored(OSError, WindowsError):
            os.makedirs(self.pushfolder_nofileinfolder)
            os.makedirs(self.pushfolder_withfileinfolder)
        f_in_folder = os.path.join(self.pushfolder_withfileinfolder, 'temp')
        with open(f_in_folder, 'wb') as tempf:
            tempf.write(b'test')
        with open(self.pushfile_success, 'wb') as tempf:
            tempf.write(b'test')

        self.adb.push(self.pushfolder_nofileinfolder, self.dstfolder_successfolder)
        self.adb.push(self.pushfolder_withfileinfolder, self.dstfolder_successfolder)
        with self.assertRaises(AdbFailException):
            self.adb.push(self.pushfolder_withfileinfolder, self.dstfolder_permissiondeny)
        self.adb.push(self.pushfile_success, self.dstfile_successfile)
        with self.assertRaises(AdbFailException):
            self.adb.push(self.pushfile_success, self.dstfolder_permissiondeny)

        pushfolderfile_in_dst = posixpath.join(self.dstfolder_successfolder, os.path.basename(f_in_folder))
        self.adb.shell('rm -rf {}'.format(pushfolderfile_in_dst))
        self.adb.shell('rm -rf {}'.format(self.dstfile_successfile))
        os.remove(f_in_folder)
        os.rmdir(self.pushfolder_nofileinfolder)
        os.rmdir(self.pushfolder_withfileinfolder)

    def test_pull_file2folder(self):
        file_list = self.adb.pull(self.pullfile_success, self.pullremote_srcfolder)
        self.assertTrue(file_list)
        target_file_path = os.path.join(tempfile.gettempdir(), u'build.prop')
        self.assertEqual(os.path.abspath(file_list[0]), target_file_path)
        with ignored(OSError):
            os.remove(target_file_path)

    def test_pull_file2file(self):
        file_list = self.adb.pull(self.pullfile_success, self.pullremote_srcfile)
        self.assertTrue(file_list)
        self.assertEqual(os.path.abspath(file_list[0]), self.pullremote_srcfile)
        with ignored(OSError):
            os.remove(self.pullremote_srcfile)

    def test_pull_folder2folder(self):
        file_list = self.adb.pull(self.pullfolder_success, self.pullremote_srcfolder)
        self.assertTrue(file_list)
        list((self.assertTrue(os.path.basename(x) in self.files_in_pullfolder_success) for x in file_list))
        for file_ in file_list:
            with ignored(OSError):
                os.remove(file_)

    def test_pull_nofile(self):
        with self.assertRaises(AdbFailException):
            self.adb.pull(self.pullfile_nofile, self.pullremote_srcfile)

    def test_pull_nofolder(self):
        with self.assertRaises(AdbFailException):
            self.adb.pull(self.pullfolder_nofolder, self.pullremote_srcfolder)

    def test_pull_permission(self):
        with self.assertRaises(AdbFailException):
            self.adb.pull(self.pullfile_permissiondeny, self.pullremote_srcfile)

class AdbShellTest(unittest.TestCase):
    valid_dut_ip = VALID_DUT_IP
    @classmethod
    def setUpClass(cls):
        cls.adb = AdbWrapper()

    @classmethod
    def tearDownClass(cls):
        del cls.adb

    def setUp(self):
        self.adb.device = multi_connect(self.adb, self.valid_dut_ip)

    def tearDown(self):
        multi_connect(self.adb)
        self.adb.device = u''
        self.adb.kill_server()

    def test_shell(self):
        stdout, _ = self.adb.shell('echo "a b \\ * ^ &"')
        self.assertTrue(stdout == u'a b \\ * ^ &')
        stdout, _ = self.adb.shell(u'echo \'中文\'')
        self.assertTrue(stdout == u'中文')

class AdbLogTest(unittest.TestCase):

    valid_dut_ip = VALID_DUT_IP
    bugreport_f = os.path.join(tempfile.gettempdir(), 'bugreport.log')
    logcat_f = os.path.join(tempfile.gettempdir(), 'test.logcat')
    logcatv_f = os.path.join(tempfile.gettempdir(), 'testv.logcat')

    @classmethod
    def setUpClass(cls):
        cls.adb = AdbWrapper()

    @classmethod
    def tearDownClass(cls):
        del cls.adb

    def setUp(self):
        self.adb.device = multi_connect(self.adb, self.valid_dut_ip)

    def tearDown(self):
        self.adb.device = u''
        self.adb.kill_server()
        with ignored(OSError):
            os.remove(self.bugreport_f)
        with ignored(OSError):
            os.remove(self.logcat_f)
        with ignored(OSError):
            os.remove(self.logcatv_f)

    def test_logcat(self):
        res, logcat_h = self.adb.logcat(self.logcat_f)
        self.assertTrue(res)
        time.sleep(5)
        logcat_h.close()
        self.assertTrue(os.path.isfile(self.logcat_f))
        self.assertGreater(os.path.getsize(self.logcat_f), 1000)
        res, logcat_h = self.adb.logcat(self.logcatv_f, params='-vtime')
        self.assertTrue(res)
        time.sleep(5)
        self.assertTrue(os.path.isfile(self.logcatv_f))
        logcat_h.close()
        self.assertGreater(os.path.getsize(self.logcatv_f), 1000)

    def test_bugreport(self):
        bug_f = self.adb.bugreport(self.bugreport_f)
        self.assertEqual(bug_f, os.path.abspath(self.bugreport_f))
        bug_b = self.adb.bugreport()
        self.assertGreater(len(bug_b), 1000)

if __name__ == "__main__":
    unittest.main()
