# -*- coding: utf-8 -*-
import time
import sys, locale
import os
sys.path.insert(1,os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
from adb_wrapper import *
if __name__ == "__main__":
    dut_exist = '10.37.132.194'
    bugreport_f = r'R:\bugreport.log'
    def temperrorprint(func, res):
        print("!!!!!!!!!!!!!!! {0}: {1}".format(func, res[1]))
        print("!!!!!!!!!!!!!!! {0}: stdout - {1!r}".format(func, res[2]))
        print("!!!!!!!!!!!!!!! {0}: stderr - {1!r}".format(func, res[3]))
    try:
        a = AdbWrapper()
        print("sys.stdout.encoding:            {}".format(sys.stdout.encoding))
        print("locale.getpreferredencoding():  {}".format(locale.getpreferredencoding()))
        print("sys.getfilesystemencoding():    {}".format(sys.getfilesystemencoding()))
        try:
            print("os.environ['PYTHONIOENCODING']: {}".format(os.environ['PYTHONIOENCODING']))
        except:
            pass
        res = a.connect(dut_exist)
        if res[0] != True: temperrorprint('connect()', res)
        # print(a.shell('id', dut_exist+':5555'))
        # print(a.shell('id', device=dut_exist+':5555'))
        a.set_device(dut_exist+':5555')
        a.set_device(b'10.37.132.194:5555')
        a.set_device('10.37.132.194:5555')
        a.set_device(u'10.37.132.194:5555')
        res = a.shell(u'echo "中文"')
        print(type(res[1]))
        print("{!r}".format(res[1]))
        # res = a.shell('echo "中文"')
        # print(type(res[1]))
        # print("{!r}".format(res))
        # # print(a.shell('id'))
        res = a.bugreport(bugreport_f)
        if res[0] != True: temperrorprint('bugreport(bugreport_f)', res)
    except KeyboardInterrupt:
        print("User CTRL+C")
    del a
