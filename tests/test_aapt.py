# -*- coding: utf-8 -*-
import unittest
import sys
import os
import re

sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
from adb_wrapper.aapt_wrapper import AaptWrapper
from adb_wrapper.aapt_wrapper import AaptFailException
from adb_wrapper.aapt_wrapper import NoAaptBinaryException

class AaptTest(unittest.TestCase):

    def setUp(self):
        self.apk = os.path.join(os.path.dirname(__file__), 'HelloWorld.apk')
        self.aapt = AaptWrapper()

    def test_dump_badging(self):
        apk_dict = self.aapt.dump('badging', self.apk)
        self.assertTrue(re.match(r'[\.0-9]+', self.aapt.binary_version))
        self.assertEqual(apk_dict['package']['name'], u'com.helloworld.android')
        self.assertEqual(apk_dict['launchable-activity']['name'], u'com.helloworld.android.HelloWorldActivity')
        self.assertEqual(apk_dict['package']['versionCode'], u'1')
        self.assertEqual(apk_dict['package']['versionName'], u'1.0')
        self.assertEqual(apk_dict['sdkVersion'], u'3')
        self.assertEqual(apk_dict['supports-screens'], [u'normal'])
        self.assertFalse(apk_dict['supports-any-density'])
        self.assertEqual(apk_dict['densities'], [u'160'])

    def test_fakeapp(self):
        with self.assertRaises(AaptFailException):
            self.aapt.dump('badging', 'fake_app.apk')

    def tearDown(self):
        del self.aapt

class NoAaptTest(unittest.TestCase):

    def test_noaapt(self):
        with self.assertRaises(NoAaptBinaryException):
            AaptWrapper(aapt_file=u'fake_aapt_path')

if __name__ == '__main__':
    unittest.main()
