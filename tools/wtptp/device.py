"""A simulated P298 / ASR1802S boot ROM, speaking WTPTP over a pipe.

The point of this file is that we do not know why the real board stops
answering after the DKB lands. Rather than guess once per power cycle, each
candidate explanation is a named behaviour model. The client is exercised
against every one of them, so whichever turns out to be true we already
handle -- and so we can see which models the client cannot distinguish, which
is where we are blind on real hardware.

Behaviour models
----------------
``mute_after_dkb``    DKB completes, then the device goes silent. This is
                      what the real board does, and the failure we are stuck on.
``stay_awake``        Device keeps answering for the FBF.
``require_valid_dkb`` DKB accepted only if it begins with the IBKD magic.
``require_timhdr``    DKB accepted only if the payload behind IBKD opens with
                      a TIM header. One level stricter.
``idle_timeout``      Device mutes if nothing arrives for ``idle_ms``. Models
                      the ~1.6 s window dmesg shows.
``reset_usb``         Device disconnects after the DKB. Distinguishes "went
                      quiet" from "actually went away", which dmesg tells
                      apart and our tool confuses.
"""

import enum
import time

from . import protocol as P


class Stage(enum.Enum):
    IDLE = "idle"
    READY = "ready"
    DOWNLOADING = "downloading"
    DONE = "done"
    MUTED = "muted"
    GONE = "gone"


class SimDevice:
    """Emulates the device side of a WTPTP session."""

    def __init__(self, *, mute_after_dkb=True, require_valid_dkb=False,
                 require_timhdr=False, idle_timeout=False, idle_ms=1600,
                 reset_usb=False, buffer_size=P.DEFAULT_BUFFER_SIZE,
                 verbose=False):
        self.mute_after_dkb = mute_after_dkb
        self.require_valid_dkb = require_valid_dkb
        self.require_timhdr = require_timhdr
        self.idle_timeout = idle_timeout
        self.idle_ms = idle_ms
        self.reset_usb = reset_usb
        self.buffer_size = buffer_size
        self.verbose = verbose

        self.stage = Stage.IDLE
        self.out = bytearray()
        self.connected = True
        self.log = []
        self.images_seen = 0

        self._rx = bytearray()
        self._expect = 0          # bytes still to come for the current image
        self._image = bytearray()
        self._last_rx = time.monotonic()

    # -- plumbing ----------------------------------------------------------

    def _say(self, msg):
        self.log.append(msg)
        if self.verbose:
            print(f"      [dev] {msg}")

    def feed(self, data: bytes):
        if not self.connected or self.stage is Stage.MUTED:
            return
        self._last_rx = time.monotonic()
        self._rx += data
        while self._rx:
            consumed = self._dispatch()
            if consumed == 0:
                break
            del self._rx[:consumed]

    def _need(self, n: int) -> bool:
        return len(self._rx) >= n

    # -- replies -----------------------------------------------------------

    def _reply_preamble(self):
        # VERIFIED: SendPreamble reads 0x26 bytes and checks status[0]==0,
        # status[1]==0xD3, status[2]==0x02.
        body = bytes((P.PLATFORM_READY_STATUS,)) + P.PREAMBLE_MAGIC[:2]
        self.out += body.ljust(P.PREAMBLE_REPLY_LEN, b"\x00")
        self.stage = Stage.READY
        self._say(f"preamble -> ready (version {P.DEVICE_VERSION:#06x})")

    def _reply_version(self):
        # Only the string form is VERIFIED, from the tool's own logs:
        #   Version: 3311   Date: 06012014   Processor: NZA3
        body = (P.DEVICE_VERSION.to_bytes(4, "little")
                + P.DEVICE_DATE.to_bytes(4, "little")
                + P.DEVICE_PROCESSOR)
        self.out += body.ljust(32, b"\x00")
        self._say("version")

    def _reply_dataheader(self):
        # Values VERIFIED from "Return flag in Dataheader CMD: 0,FDSwitch is 1,
        # BufferSize is 0xF8". Offsets INFERRED.
        body = (bytes((0, P.FDSWITCH_REPORTED))
                + self.buffer_size.to_bytes(2, "little"))
        self.out += body.ljust(16, b"\x00")
        self.stage = Stage.DOWNLOADING
        self._say(f"dataheader -> buffer {self.buffer_size:#06x}")

    def _ack(self):
        """Per-chunk acknowledgement.

        VERIFIED only that the device reports "Platform ready status: 0" as a
        single byte. The trailing magic echo here is INFERRED.
        """
        self.out += bytes((0,)) + P.PREAMBLE_MAGIC

    # -- dispatch ----------------------------------------------------------

    def _dispatch(self) -> int:
        # The preamble is 4 bytes on the wire, not 8, so it is recognised
        # before we demand a full header.
        if len(self._rx) >= 4 and bytes(self._rx[:4]) == P.CMD_PREAMBLE[:4]:
            self._reply_preamble()
            return 4

        if not self._need(P.HEADER_LEN):
            return 0

        cmd = bytes(self._rx[:4])
        length = int.from_bytes(self._rx[4:8], "little")

        if cmd == bytes((0x03, 0x00, 0x00, 0x00)):          # version
            self._reply_version()
            return P.HEADER_LEN

        if cmd == P.CMD_DATAHEADER[:4]:                     # start of image
            if not self._need(P.HEADER_LEN + 4):
                return 0
            self._expect = int.from_bytes(self._rx[8:12], "little")
            self._image = bytearray()
            self._reply_dataheader()
            return P.HEADER_LEN + 4

        if cmd == P.CMD_UPLOADDATAHDR[:4]:                  # image body
            if not self._need(P.HEADER_LEN + length):
                return 0
            body = self._rx[P.HEADER_LEN:P.HEADER_LEN + length]
            self._image += body

            # Reject a bad DKB as soon as the magic is visible, not after
            # the whole image has been transferred. This is what makes the
            # "bad DKB" models distinguishable from the "mutes after DKB"
            # one: the client sees the failure arrive during image 1 rather
            # than at image 2, which is a difference it can act on.
            if self.images_seen == 0 and len(self._image) >= 4:
                if (self.require_valid_dkb
                        and bytes(self._image[:4]) != P.IBKD_MAGIC):
                    self._say("DKB rejected: bad IBKD magic (mid-image) -> mute")
                    self.stage = Stage.MUTED
                    self._image = bytearray()
                    return P.HEADER_LEN + length
                if self.require_timhdr:
                    body2 = bytes(self._image[len(P.IBKD_MAGIC):])
                    if len(body2) >= 8:
                        ok = (int.from_bytes(body2[:4], "little") == P.TIM_VERSION
                              and body2[4:8] == P.TIM_MAGIC)
                        if not ok:
                            self._say("DKB rejected: no TIM header (mid-image) -> mute")
                            self.stage = Stage.MUTED
                            self._image = bytearray()
                            return P.HEADER_LEN + length

            self._ack()
            return P.HEADER_LEN + length

        if cmd[:1] == P.CMD_VERIFYIMAGE[:1]:                # end of image
            self._finish_image()
            self._ack()
            return P.HEADER_LEN

        self._say(f"unknown cmd {cmd.hex(' ')}")
        return P.HEADER_LEN

    def _finish_image(self):
        self.images_seen += 1
        n = self.images_seen
        payload = bytes(self._image)
        self._image = bytearray()
        self._expect = 0
        self._say(f"image {n} complete, {len(payload)} bytes")

        if n == 1:
            if self.require_valid_dkb and not payload.startswith(P.IBKD_MAGIC):
                self._say("DKB rejected: bad IBKD magic -> mute")
                self.stage = Stage.MUTED
                return
            if self.require_timhdr:
                body = payload[len(P.IBKD_MAGIC):]
                if (len(body) < 8
                        or int.from_bytes(body[:4], "little") != P.TIM_VERSION
                        or body[4:8] != P.TIM_MAGIC):
                    self._say("DKB rejected: no TIM header -> mute")
                    self.stage = Stage.MUTED
                    return
            if self.mute_after_dkb:
                self._say("DKB complete -> muting (this is the real board)")
                self.stage = Stage.MUTED
                return

        self.stage = Stage.DONE

    # -- idle timer --------------------------------------------------------

    def serve(self):
        if not self.idle_timeout:
            return
        while self.connected and self.stage is not Stage.MUTED:
            if (time.monotonic() - self._last_rx) * 1000 > self.idle_ms:
                self._say(f"idle > {self.idle_ms} ms -> muting")
                self.stage = Stage.MUTED
                return
            time.sleep(0.02)


MODELS = {
    "mute_after_dkb":    dict(mute_after_dkb=True),
    "stay_awake":        dict(mute_after_dkb=False),
    "require_valid_dkb": dict(mute_after_dkb=True, require_valid_dkb=True),
    "require_timhdr":    dict(mute_after_dkb=True, require_timhdr=True),
    "reset_usb":         dict(mute_after_dkb=True, reset_usb=True),
    "idle_timeout":      dict(mute_after_dkb=False, idle_timeout=True),
}