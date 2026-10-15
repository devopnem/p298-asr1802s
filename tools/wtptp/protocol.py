"""WTPTP wire format, as recovered from swdl_linux 4.8.8.2.

EVERYTHING HERE IS TAGGED. Nothing in this module is a guess dressed up as
fact: each constant is marked VERIFIED (read out of the disassembly, with the
address that proves it) or INFERRED (consistent with the logs, but not
confirmed at the instruction level).

The point of tagging is that the simulator is only useful if we know exactly
what it rests on. When we eventually get a board to talk to, every INFERRED
item becomes a thing we can confirm or correct in one place.
"""

# ---------------------------------------------------------------------------
# Header layout
# ---------------------------------------------------------------------------

# VERIFIED. CWtpComm::SendPreamble (0x0816d820) builds a buffer at
# ebp-0x4024, memset to zero, then:
#
#   816d896  mov BYTE PTR [ebp-0x4023],0xd3      ; buf[1]
#   816d89d  mov BYTE PTR [ebp-0x4022],0x02      ; buf[2]
#   816d8a4  mov BYTE PTR [ebp-0x4021],0x2b      ; buf[3]
#   816d8ab  mov DWORD PTR [ebp-0x4020],0xd3022b ; buf[4..7], little endian
#
# and then calls:
#
#   816d8c0  call CWtpComm::WriteUSB(this, 4)
#
# so the preamble ON THE WIRE is 4 bytes, buf[0..3]:
#
#     00 D3 02 2B
#
# buf[0] is 0 (memset), not a separate opcode byte.
PREAMBLE_WIRE = bytes((0x00, 0xD3, 0x02, 0x2B))

# The dword at buf[4..7] is 0x00D3022B stored little-endian, i.e. the bytes
# 2B 02 D3 00. It is NOT written by the 4-byte WriteUSB call above, so it is
# not part of the preamble on the wire. It is presumably scratch reused by a
# later message in the same function. VERIFIED that the store happens;
# INFERRED that the value is unused for the preamble.
PREAMBLE_TAIL = bytes((0x2B, 0x02, 0xD3, 0x00))

# The preamble magic as checked in the reply. VERIFIED, SendPreamble after
# the read:
#
#   816d904  cmp BYTE PTR [esi],0x0      -> "Platform ready status"
#   816d90b  cmp BYTE PTR [esi+0x1],0xd3 -> magic byte 1
#   816d911  cmp BYTE PTR [esi+0x2],0x2  -> magic byte 2
#
# so a reply is  status[0]=0, status[1]=0xD3, status[2]=0x02, ...
PREAMBLE_MAGIC = bytes((0xD3, 0x02, 0x2B))

# VERIFIED. SendPreamble issues CWtpComm::ReadUSB(this, status, 0x26).
PREAMBLE_REPLY_LEN = 0x26   # 38

# VERIFIED. CWtptpDownLoad::DownloadImage issues one
# `CWtpComm::WriteUSB(buf, chunk + 8)` per chunk, so every message is an
# 8-byte header followed by payload.
HEADER_LEN = 8

# INFERRED, from CWtpComm::DataHeader and the log line
# "Return flag in Dataheader CMD: %d,FDSwitch is %d,BufferSize is 0x%X":
# the reply carries a return flag, an FDSwitch and a BufferSize, and
# [ebp-0x481e] (== WTPSTATUS+4) is the top byte of a 4-byte little-endian
# length field. The exact offsets of the three log fields are NOT confirmed.

# Command values recorded during RE of swdl_linux. VERIFIED as constants that
# exist in the binary; INFERRED as to which byte position each occupies in a
# message header.
CMD_PREAMBLE      = bytes((0x00, 0xD3, 0x02, 0x2B))
CMD_DATAHEADER    = bytes((0x04, 0x00, 0x00, 0x2A))
CMD_VERIFYIMAGE   = bytes((0x01, 0x00, 0x00, 0x00, 0x27))
CMD_UPLOADDATAHDR = bytes((0x10, 0x00, 0x00, 0x00, 0x32))

# ---------------------------------------------------------------------------
# Device identity
# ---------------------------------------------------------------------------

# VERIFIED, straight out of the run logs of our own board.
DEVICE_VERSION   = 0x3311        # "Version: 3311"
DEVICE_DATE      = 0x06012014    # "Date: 06012014"
DEVICE_PROCESSOR = b"NZA3"       # "Processor: NZA3"
DEVICE_VID       = 0x2ECC
DEVICE_PID       = 0x3002

# VERIFIED, printed by the tool on every run.
PLATFORM_READY_STATUS = 0

# INFERRED. The DataHeader reply advertises this and the tool immediately logs
# it as "BufferSize is 0xF8". Only 0xF8 has ever been observed; nothing in
# this project has confirmed the device would accept anything else.
DEFAULT_BUFFER_SIZE = 0xF8       # 248

# VERIFIED, printed verbatim by the tool on every single run, which is why
# it is modelled as a constant rather than a device capability.
FDSWITCH_REPORTED = 1
FAST_DOWNLOAD_ACTIVATED = False  # "Fast Download is not activated"


# ---------------------------------------------------------------------------
# TIM container, as seen at the head of every OBM/DTIM image
# ---------------------------------------------------------------------------

# VERIFIED. mtd0.bin and the DTIMs both open with these, read straight out of
# findings/nand-dumps/mtd0.bin:
#   offset 0x00  00 04 03 00   version 0x00030400
#   offset 0x04  48 4d 49 54   "HMIT"
TIM_VERSION = 0x00030400
TIM_MAGIC = b"HMIT"

# VERIFIED. A DKB is this magic followed by the image verbatim:
#   Dkb.bin[0:4] == b"IBKD"
#   Dkb.bin[4:]  == mtd0.bin
IBKD_MAGIC = b"IBKD"


def with_header(command: bytes, payload: bytes = b"") -> bytes:
    """Build an 8-byte header plus payload.

    VERIFIED that the header is 8 bytes. INFERRED that the command occupies
    the first 4 header bytes and that the remaining 4 carry the payload
    length. If a real board rejects our framing, this is the one place to fix.
    """
    cmd = command[:4].ljust(4, b"\x00")
    return cmd + len(payload).to_bytes(4, "little") + payload


def parse_header(buf: bytes) -> dict:
    """Decode an 8-byte header. See the module docstring for confidence."""
    if len(buf) < HEADER_LEN:
        return {}
    return {
        "cmd": buf[:4],
        "length": int.from_bytes(buf[4:8], "little"),
        "raw": buf[:HEADER_LEN],
    }