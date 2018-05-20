# -*- coding: utf-8 -*-

def u(value):
    return value.decode('UTF-8') if isinstance(value, bytes) else value

class Intent(object):
    def __init__(self):
        self._hasIntentInfo = False
        self._action = None
        self._data = None
        self._type = None
        self._categories = []
        self._component = None
        self._flag = None
        self._selector = False
        self._es = []
        self._esn = []
        self._ei = []
        self._eu = []
        self._ecn = []
        self._eia = []
        self._el = []
        self._ela = []
        self._ef = []
        self._efa = []
        self._ez = []
        self._flags = set()

    def __iter__(self):
        args = []
        if self._action:
            args.extend([u'-a', u(self._action)])
        if self._data:
            args.extend([u'-d', u(self._data)])
        if self._type:
            args.extend([u'-t', u(self._type)])
        for category in self._categories:
            args.extend([u'-c', u(category)])
        if self._component:
            args.extend([u'-n', u(self._component)])
        if self._flag:
            args.extend([u'-f', u(self._flag)])
        if self._selector:
            args.append(u'--selector')
        for es in self._es:
            for key, value in es.items():
                args.extend([u'--es', u(key), u(value)])
        for esn in self._esn:
            for key in esn:
                args.extend([u'--esn', u(key)])
        for ei in self._ei:
            for key, value in ei.items():
                args.extend([u'--ei', u(key), u(str(value))])
        for eu in self._eu:
            for key, value in eu.items():
                args.extend([u'--eu', u(key), u(value)])
        for ecn in self._ecn:
            for key, value in ecn.items():
                args.extend([u'--ecn', u(key), u(value)])
        for eia in self._eia:
            for key, values in eia.items():
                args.extend([u'--eia', u(key), u','.join((u(str(value)) for value in values))])
        for el in self._el:
            for key, value in el.items():
                args.extend([u'--el', u(key), u(value)])
        for ela in self._ela:
            for key, values in ela.items():
                args.extend([u'--ela', u(key), u','.join((u(str(value)) for value in values))])
        for ef in self._ef:
            for key, value in ef.items():
                args.extend([u'--ef', u(key), u(str(value))])
        for efa in self._efa:
            for key, values in efa.items():
                args.extend([u'--efa', u(key), u','.join((u(str(value)) for value in values))])
        for ez in self._ez:
            for key, value in ez.items():
                args.extend([u'--ez', u(key), u'true' if value else u'false'])
        if self._flags:
            args.extend(self._flags)
        iter(args)

    def setAction(self, action):
        self._action = action

    def setData(self, data):
        self._data = data

    def setType(self, intentType):
        self._type = intentType

    def addCategory(self, category):
        self._categories.append(category)

    def setComponent(self, component):
        self._component = component

    def setPackage(self, package):
        self._package = package

    def selector(self):
        self._selector = True

    def putExtraString(self, key, value):
        self._es.append({key: value})

    def putExtraNull(self, key):
        self._esn.append(key)

    def putExtraInt(self, key, value):
        self._ei.append({key: value})

    def putExtraUri(self, key, value):
        self._eu.append({key: value})

    def putExtraComponent(self, key, value):
        self._ecn.append({key: value})

    def putExtraArrayInt(self, key, *values):
        self._eia.append({key: values})

    def putExtraLong(self, key, value):
        self._el.append({key: value})

    def putExtraArrayLong(self, key, *values):
        self._ela.append({key: values})

    def putExtraFloat(self, key, value):
        self._ef.append({key: value})

    def putExtraArrayFloat(self, key, *values):
        self._efa.append({key: values})

    def putExtraBoolean(self, key, value):
        self._ez.append({key: value})

    def setFlags(self, flag):
        self._flag = flag

    def grant_read_uri_permission(self):
        self._flags.add('--grant-read-uri-permission')

    def grant_write_uri_permission(self):
        self._flags.add('--grant-write-uri-permission')

    def grant_persistable_uri_permission(self):
        self._flags.add('--grant-persistable-uri-permission')

    def grant_prefix_uri_permission(self):
        self._flags.add('--grant-prefix-uri-permission')

    def exclude_stopped_packages(self):
        self._flags.add('--exclude-stopped-packages')

    def include_stopped_packages(self):
        self._flags.add('--include-stopped-packages')

    def debug_log_resolution(self):
        self._flags.add('--debug-log-resolution')

    def activity_brought_to_front(self):
        self._flags.add('--activity-brought-to-front')

    def activity_clear_top(self):
        self._flags.add('--activity-clear-top')

    def activity_clear_when_task_reset(self):
        self._flags.add('--activity-clear-when-task-reset')

    def activity_exclude_from_recents(self):
        self._flags.add('--activity-exclude-from-recents')

    def activity_launched_from_history(self):
        self._flags.add('--activity-launched-from-history')

    def activity_multiple_task(self):
        self._flags.add('--activity-multiple-task')

    def activity_no_animation(self):
        self._flags.add('--activity-no-animation')

    def activity_no_history(self):
        self._flags.add('--activity-no-history')

    def activity_no_user_action(self):
        self._flags.add('--activity-no-user-action')

    def activity_previous_is_top(self):
        self._flags.add('--activity-previous-is-top')

    def activity_reorder_to_front(self):
        self._flags.add('--activity-reorder-to-front')

    def activity_reset_task_if_needed(self):
        self._flags.add('--activity-reset-task-if-needed')

    def activity_single_top(self):
        self._flags.add('--activity-single-top')

    def activity_clear_task(self):
        self._flags.add('--activity-clear-task')

    def activity_task_on_home(self):
        self._flags.add('--activity-task-on-home')

    def receiver_registered_only(self):
        self._flags.add('--receiver-registered-only')

    def receiver_replace_pending(self):
        self._flags.add('--receiver-replace-pending')

    def receiver_foreground(self):
        self._flags.add('--receiver-foreground"')

    def receiver_no_abort(self):
        self._flags.add('--receiver-no-abort')

    def receiver_include_background(self):
        self._flags.add('--receiver-include-background')
