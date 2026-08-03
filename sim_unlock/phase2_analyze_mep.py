#!/usr/bin/env python3
"""
Phase 2: Offline MEP and NVM analysis script.
Parses mtd1_cp_reliabledata.bin locally to search for MEP files, lock structures,
MCC/MNC configurations, and specific strings like '80822207'.
"""

import os
import re

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
mtd1_path = os.path.join(OUT_DIR, "mtd1_cp_reliabledata.bin")

def main():
    print(f"[*] Analyzing {mtd1_path} ...")
    if not os.path.exists(mtd1_path):
        print("[-] mtd1 dump not found! Run Phase 1 first.")
        return

    with open(mtd1_path, "rb") as f:
        data = f.read()

    print(f"[+] Loaded {len(data)} bytes.")

    report_path = os.path.join(OUT_DIR, "mep_analysis_report.txt")
    with open(report_path, "w", encoding="utf-8") as rep:
        rep.write("=== Notion R291 MTD1 (cp_reliabledata) MEP Analysis Report ===\n\n")

        # 1. Search for known strings
        rep.write("--- 1. String Search (ASCII / UTF-16) ---\n")
        # Extract all printable strings of length >= 4
        strings = re.findall(b"[ -~]{4,}", data)
        found_keywords = []
        for s in strings:
            s_dec = s.decode(errors="ignore")
            if any(k in s_dec.lower() for k in ["mep", "sim", "lock", "nvm", "gki", "ttr", "pldt", "ooredoo", "80822207", "imei"]):
                found_keywords.append(s_dec)
                rep.write(f"Found: {s_dec}\n")

        # 2. Search for MEP.bin or similar structures
        rep.write("\n--- 2. MEP / NVM File Signatures & Offsets ---\n")
        # Search for patterns like MEP
        mep_offsets = [i for i in range(len(data) - 3) if data[i:i+3] == b"MEP"]
        for off in mep_offsets:
            chunk = data[max(0, off-16):min(len(data), off+64)]
            rep.write(f"Offset 0x{off:X}: chunk = {chunk}\n")

        # 3. Search for occurrences of '80822207'
        rep.write("\n--- 3. Occurrences of '80822207' (MEP Key/ID) ---\n")
        target_sig = b"80822207"
        for i in range(len(data) - len(target_sig)):
            if data[i:i+len(target_sig)] == target_sig:
                chunk = data[max(0, i-32):min(len(data), i+64)]
                rep.write(f"Offset 0x{i:X}: {chunk}\n")

        # 4. Dump entropy or structure summary
        rep.write(f"\nTotal size: {len(data)} bytes\n")

    print(f"[+] Analysis complete. Report written to {report_path}")

if __name__ == "__main__":
    main()
