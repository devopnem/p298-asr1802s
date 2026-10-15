"""The WTPTP client state machine.

Deliberately transport-agnostic. Everything it knows about the device comes
from protocol.py; everything it knows about USB comes from the transport.
That split is the whole point: it is what lets the same code run against the
simulator and, later, against a real board.
"""

from . import protocol as P


class WtptpError(Exception):
    pass


class DeviceMuted(WtptpError):
    """The device stopped answering mid-session."""


class WtptpClient:
    def __init__(self, transport, chunk_size=None, log=print):
        self.t = transport
        self.log = log
        self.chunk_size = chunk_size      # None = use the device's BufferSize
        self.buffer_size = P.DEFAULT_BUFFER_SIZE
        self.images = []

    # -- low level ---------------------------------------------------------

    def _xfer(self, msg: bytes, want: int) -> bytes:
        self.t.write(msg)
        if want <= 0:
            return b""
        reply = self.t.read(want)
        if not reply:
            raise DeviceMuted(
                f"no reply to {msg[:4].hex(' ')} ({len(msg)} bytes out)")
        return reply

    # -- session -----------------------------------------------------------

    def send_preamble(self):
        """VERIFIED against SendPreamble at 0x0816d820: 4 bytes out,
        0x26 back, status[0] must be 0 and status[1..2] the D3 02 magic."""
        reply = self._xfer(P.PREAMBLE_WIRE, P.PREAMBLE_REPLY_LEN)
        if reply[0] != P.PLATFORM_READY_STATUS:
            raise WtptpError(f"bad ready status {reply[0]:#04x}")
        if reply[1:3] != P.PREAMBLE_MAGIC[:2]:
            raise WtptpError(f"bad preamble echo {reply[1:3].hex(' ')}")
        self.log(f"  ready status {reply[0]}, magic {reply[1:3].hex(' ')}")

    def get_version(self):
        """INFERRED command byte. Only the reply text is VERIFIED."""
        reply = self._xfer(P.with_header(bytes((0x03, 0x00, 0x00, 0x00))), 32)
        version = int.from_bytes(reply[0:4], "little")
        date = int.from_bytes(reply[4:8], "little")
        proc = reply[8:11]
        self.log(f"  Version: {version}  Date: {date:08X}  Processor: {proc.decode()}")
        return version, date, proc

    def data_header(self, length: int) -> int:
        """Announce an image of `length` bytes; returns the chunk size to use.

        VERIFIED that the reply advertises a BufferSize the tool logs as
        "BufferSize is 0x%X". INFERRED that we should honour it unless the
        caller overrides -- which is exactly what swdl_chunksize_patch.py
        does on the real tool.
        """
        msg = P.with_header(P.CMD_DATAHEADER[:4],
                            length.to_bytes(4, "little"))
        reply = self._xfer(msg, 16)
        advertised = int.from_bytes(reply[2:4], "little")
        self.buffer_size = self.chunk_size or advertised or P.DEFAULT_BUFFER_SIZE
        self.log(f"  device BufferSize {advertised:#06x}; using {self.buffer_size:#06x}")
        return self.buffer_size

    def send_image(self, name: str, payload: bytes):
        """Full DKB/FBF send: data header, chunks, verify.

        VERIFIED that DownloadImage sends `chunk + 8` bytes per chunk and
        that the tool prints "Completed DownLoad file" when a whole image
        goes through.
        """
        self.log(f"  -> {name} ({len(payload)} bytes)")
        chunk = self.data_header(len(payload))
        sent = 0
        while sent < len(payload):
            piece = payload[sent:sent + chunk]
            self.t.write(P.with_header(P.CMD_UPLOADDATAHDR[:4], piece))
            self.t.read(4)          # per-chunk ack
            sent += len(piece)
        self.t.write(P.with_header(P.CMD_VERIFYIMAGE[:4]))
        self.t.read(4)
        self.log(f"  <- Completed DownLoad file: {name}")

    def run(self, dkb: bytes, fbf: bytes):
        """The whole session, in the order the vendor tool uses."""
        self.log("preamble")
        self.send_preamble()
        self.log("version")
        self.get_version()

        self.log("image 1 (DKB / download kernel)")
        self.send_image("DKB_ntimheader.bin", dkb)

        self.log("image 2 (FBF / flash payload)")
        self.send_image("FBF_Ntimheader.bin", fbf)
        return True