# extract_qspi.py - Ghidra headless post-script
# Decompiles every function that references a "qspi"/"spi_nand" string in the
# vendor kernel Image, so we can read the exact QSPI register offsets + the
# IP-command/LUT program order. Run via analyzeHeadless -postScript.
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.listing import Function

args = getScriptArgs()
outpath = args[0] if args and len(args) > 0 else "/tmp/qspi_decomp.txt"

program = currentProgram
fm = program.getFunctionManager()
listing = program.getListing()
rm = program.getReferenceManager()

# Build string map (addr -> text)
string_map = {}
it = listing.getDefinedData(True)
while it.hasNext():
    d = it.next()
    dt = d.getDataType()
    if dt is not None and "string" in dt.getName().lower():
        try:
            val = str(d.getValue())
        except Exception:
            val = None
        if val:
            string_map[long(d.getAddress().getOffset())] = val

import re
interesting = [a for a, t in string_map.items()
               if re.search(r'qspi|spi_nand|spinand|pxa3xx_bbm', t, re.I)]

funcs = set()
for addr in interesting:
    for r in rm.getReferencesTo(toAddr(addr)):
        f = fm.getFunctionContaining(r.getFromAddress())
        if f:
            funcs.add(f)

out = open(outpath, "w")
out.write("Image base: 0x%x\n" % program.getImageBase().getOffset())
out.write("strings matched: %d, functions: %d\n" % (len(interesting), len(funcs)))

dec = DecompInterface()
dec.openProgram(program)
mon = ConsoleTaskMonitor()

for f in sorted(funcs, key=lambda x: x.getEntryPoint().getOffset()):
    out.write("\n\n===== FUNCTION %s @ 0x%x =====\n"
              % (f.getName(), f.getEntryPoint().getOffset()))
    res = dec.decompileFunction(f, 60, mon)
    df = res.getDecompiledFunction() if res else None
    if df is not None:
        out.write(df.getC())
    else:
        out.write("(decompile failed)\n")
out.close()
print("WROTE", outpath, "funcs", len(funcs))
