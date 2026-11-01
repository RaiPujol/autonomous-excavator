"""Broadcast frames from a Mac with CoreBluetooth (service-UUID advertising)."""
from .protocol import NAME


class MacBroadcaster:
    def __init__(self, timeout=5.0):
        import time
        from CoreBluetooth import (CBAdvertisementDataLocalNameKey,
                                   CBAdvertisementDataServiceUUIDsKey,
                                   CBPeripheralManager, CBUUID)
        from Foundation import NSDate, NSObject, NSRunLoop

        class _Delegate(NSObject):
            def peripheralManagerDidUpdateState_(self, pm):
                pass

            def peripheralManagerDidStartAdvertising_error_(self, pm, err):
                if err:
                    print("advertising error:", err)

        self._k_uuids = CBAdvertisementDataServiceUUIDsKey
        self._k_name = CBAdvertisementDataLocalNameKey
        self._CBUUID = CBUUID
        self._NSDate, self._NSRunLoop = NSDate, NSRunLoop
        self._delegate = _Delegate.alloc().init()
        self.pm = CBPeripheralManager.alloc().initWithDelegate_queue_(self._delegate, None)
        t0 = time.time()
        while self.pm.state() != 5:  # CBManagerStatePoweredOn
            self.pump(0.1)
            if time.time() - t0 > timeout:
                raise RuntimeError("Bluetooth not ready. Is it on, and is Terminal allowed in "
                                   "System Settings > Privacy & Security > Bluetooth?")

    def pump(self, sec):
        self._NSRunLoop.currentRunLoop().runUntilDate_(
            self._NSDate.dateWithTimeIntervalSinceNow_(sec))

    def send(self, uuid):
        self.pm.stopAdvertising()
        self.pm.startAdvertising_({self._k_uuids: [self._CBUUID.UUIDWithString_(uuid)],
                                   self._k_name: NAME})

    def stop(self):
        self.pm.stopAdvertising()


class DryRunBroadcaster:
    """No Bluetooth. For testing the UI on any machine."""

    def pump(self, sec):
        import time
        time.sleep(sec)

    def send(self, uuid):
        pass

    def stop(self):
        pass
