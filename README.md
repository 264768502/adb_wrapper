# adb_wrapper
A Python wrapper for adb command (Windows/Linux) based on subprocess

This is a Google Android adb wrapper (adb.exe/adb).  
It can offer basic connect, disconnect, shell, and etc.  
Support both Windows/Ubuntu Python2/Python3  
Verified at Windows7/Ubuntu16 Python2.7.11/Python3.5.1  
Note: All input cmd should be str(Encoding should be ADB_ENC) or Unicode  
After run any adb command, there will be a adb daemon in backgroud created by adb automatically  
To kill it manually, you need use kill_server  

So far, it support below adb function:
For any detail usage, please see as doc string
* start-server
* kill-server
* devices
* connect
* disconnect
* bugreport
* push
* pull
* remount
* root
* unroot (not support on Ubuntu adb from apt android-tools-adb)
* reboot
* reboot-bootloader
* shell
* install
* uninstall
* wait-for-device
* disable-verity
* enable-verity (not support on Ubuntu adb from apt android-tools-adb)
* logcat
* shell2file

Example:
```Python
    from adb_wrapper import AdbWrapper
    a = AdbWrapper() # Auto Find adb in system PATH or Environment
    b = AdbWrapper(adb_file=r'C:\adb.exe') # User define adb PATH
    a.connect("192.168.1.2")
```
