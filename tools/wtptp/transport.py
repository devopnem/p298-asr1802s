"""Transports. The client never touches USB directly, so it can be driven
from a pipe (tests, the simulator) or from a real device node.
"""

import os


class Transport:
    """Minimal duplex byte channel."""

    def write(self, data: bytes):
        raise NotImplementedError

    def read(self, n: int) -> bytes:
        raise NotImplementedError

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class LoopbackTransport(Transport):
    """Client and SimDevice wired back to back in this process."""

    def __init__(self, device):
        self.device = device

    def write(self, data: bytes):
        self.device.feed(data)

    def read(self, n: int) -> bytes:
        if len(self.device.out) >= n:
            got = bytes(self.device.out[:n])
            del self.device.out[:n]
            return got
        # Not enough buffered: the real device would block here. For a
        # simulator we would rather return what we have than deadlock, but
        # say so loudly, because a short read is a protocol error upstream.
        got = bytes(self.device.out)
        self.device.out.clear()
        if got:
            print(f"    [warn] short read: wanted {n}, got {len(got)}")
        return got

    def close(self):
        pass


class UsbfsTransport(Transport):
    """Raw usbfs. No libusb, no pyusb -- just the device node.

    The kernel's usbfs gives bulk endpoints through USBDEVFS_BULK. We claim
    interface 0 the way the vendor tool does (it does not, which is why it
    logs "did not claim interface 0 before use"; claiming is the correct
    thing and avoids EBUSY surprises later).
    """

    USBDEVFS_CLAIMINTERFACE = 0x80045504
    USBDEVFS_BULK = 0x80045505
    USBDEVFS_RELEASEINTERFACE = 0x80045514
    USBDEVFS_GET_MAX_PACKET = 0x80085513

    def __init__(self, path: str, ep_in: int, ep_out: int, iface: int = 0):
        import fcntl
        import struct
        self._fcntl = fcntl
        self._struct = struct
        self.path = path
        self.ep_in = ep_in
        self.ep_out = ep_out
        self.iface = iface
        self.fd = os.open(path, os.O_RDWR)
        fcntl.ioctl(self.fd, self.USBDEVFS_CLAIMINTERFACE, iface)

    def _bulk(self, ep: int, data: bytes = b"", length: int = 0):
        buf = data if data else b"\x00" * length
        payload = self._struct.pack("iii", 0x800, 0, 0) + self._struct.pack(
            "iII", ep, len(buf), 0)
        ret = self._fcntl.ioctl(self.fd, self.USBDEVFS_BULK, payload)
        # ioctl returns the byte count packed into the return value
        return ret & 0xFFFF if ret >= 0 else ret

    def write(self, data: bytes):
        sent = 0
        while sent < len(data):
            sent += self._bulk(self.ep_out, data[sent:sent + 4096])

    def read(self, n: int) -> bytes:
        return self._bulk(self.ep_in, b"", n)[:n]

    def close(self):
        if self.fd >= 0:
            self._fcntl.ioctl(self.fd, self.USBDEVFS_RELEASEINTERFACE, self.iface)
            os.close(self.fd)
            self.fd = -1