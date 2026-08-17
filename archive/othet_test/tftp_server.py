#!/usr/bin/env python3
"""Simple TFTP server using Python sockets"""
import socket
import threading
import os
import sys

TFTP_PORT = 69
TFTP_ROOT = "/tmp/tftpboot"

# TFTP opcodes
RRQ = 1
WRQ = 2
DATA = 3
ACK = 4
ERROR = 5

def handle_client(data, addr, sock):
    if len(data) < 2:
        return
    opcode = int.from_bytes(data[0:2], 'big')
    if opcode == RRQ:
        # Read request
        parts = data[2:].split(b'\x00')
        filename = parts[0].decode('latin-1', errors='replace')
        filepath = os.path.join(TFTP_ROOT, filename)
        print(f"[TFTP] RRQ: {filename} from {addr}")
        if os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                content = f.read()
            # Send data in 512-byte blocks
            block_id = 1
            offset = 0
            while offset < len(content):
                chunk = content[offset:offset+512]
                pkt = b'\x00\x03' + block_id.to_bytes(2, 'big') + chunk
                sock.sendto(pkt, addr)
                print(f"  [TFTP] Sent block {block_id}, {len(chunk)} bytes")
                # Wait for ACK
                try:
                    ack_data, _ = sock.recvfrom(516)
                    if int.from_bytes(ack_data[0:2], 'big') == ACK:
                        ack_block = int.from_bytes(ack_data[2:4], 'big')
                        if ack_block != block_id:
                            print(f"  [TFTP] ACK mismatch: expected {block_id}, got {ack_block}")
                            break
                except:
                    print(f"  [TFTP] Timeout waiting for ACK")
                    break
                block_id += 1
                if block_id > 65535:
                    block_id = 1
                offset += 512
            print(f"  [TFTP] Transfer complete: {len(content)} bytes")
        else:
            err_pkt = b'\x00\x05\x00\x05\x00File not found\x00'
            sock.sendto(err_pkt, addr)
            print(f"  [TFTP] File not found: {filename}")
    elif opcode == WRQ:
        filename = data[2:].split(b'\x00')[0].decode('latin-1', errors='replace')
        print(f"[TFTP] WRQ: {filename} from {addr}")
        # Send ACK 0 to start
        ack_pkt = b'\x00\x04\x00\x00'
        sock.sendto(ack_pkt, addr)
        print(f"  [TFTP] Ready to receive: {filename}")

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", TFTP_PORT))
    print(f"[TFTP] Server listening on 0.0.0.0:{TFTP_PORT}, root={TFTP_ROOT}")
    print(f"[TFTP] Files: {os.listdir(TFTP_ROOT)}")

    while True:
        try:
            data, addr = sock.recvfrom(516)
            t = threading.Thread(target=handle_client, args=(data, addr, sock))
            t.daemon = True
            t.start()
        except KeyboardInterrupt:
            print("\n[TFTP] Shutting down")
            sock.close()
            break
        except Exception as e:
            print(f"[TFTP] Error: {e}")

if __name__ == "__main__":
    main()
