// ExtractQspi.java - Ghidra headless post-script (Java)
// Decompiles every function referencing a qspi/spi_nand string so we can read
// the exact QSPI register offsets + IP-command/LUT program order.
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.data.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.io.*;
import java.util.*;
import java.util.regex.*;

public class ExtractQspi extends GhidraScript {

    public void run() throws Exception {
        String outpath = (getScriptArgs() != null && getScriptArgs().length > 0)
                ? getScriptArgs()[0] : "/tmp/qspi_decomp.txt";

        Program program = currentProgram;
        FunctionManager fm = program.getFunctionManager();
        Listing listing = program.getListing();
        ReferenceManager rm = program.getReferenceManager();

        // Build string map: addr -> text
        Map<Long, String> stringMap = new HashMap<>();
        DataIterator di = listing.getDefinedData(true);
        while (di.hasNext()) {
            Data d = di.next();
            DataType dt = d.getDataType();
            if (dt != null && dt.getName().toLowerCase().contains("string")) {
                Object v = d.getValue();
                if (v instanceof String) {
                    stringMap.put(d.getAddress().getOffset(), (String) v);
                }
            }
        }

        Pattern pat = Pattern.compile("qspi|spi_nand|spinand|pxa3xx_bbm", Pattern.CASE_INSENSITIVE);
        Set<Long> interesting = new HashSet<>();
        for (Map.Entry<Long, String> e : stringMap.entrySet()) {
            if (pat.matcher(e.getValue()).find()) interesting.add(e.getKey());
        }

        Set<Function> funcs = new HashSet<>();
        for (long addr : interesting) {
            for (Reference r : rm.getReferencesTo(toAddr(addr))) {
                Function f = fm.getFunctionContaining(r.getFromAddress());
                if (f != null) funcs.add(f);
            }
        }

        BufferedWriter out = new BufferedWriter(new FileWriter(outpath));
        out.write("Image base: 0x" + Long.toHexString(program.getImageBase().getOffset()) + "\n");
        out.write("strings matched: " + interesting.size() + ", functions: " + funcs.size() + "\n");

        DecompInterface dec = new DecompInterface();
        dec.openProgram(program);
        TaskMonitor mon = new ConsoleTaskMonitor();

        List<Function> flist = new ArrayList<>(funcs);
        flist.sort(Comparator.comparingLong(f -> f.getEntryPoint().getOffset()));

        for (Function f : flist) {
            out.write("\n\n===== FUNCTION " + f.getName() + " @ 0x"
                    + Long.toHexString(f.getEntryPoint().getOffset()) + " =====\n");
            DecompileResults res = dec.decompileFunction(f, 60, mon);
            if (res != null && res.getDecompiledFunction() != null) {
                out.write(res.getDecompiledFunction().getC());
            } else {
                out.write("(decompile failed)\n");
            }
        }
        out.close();
        println("WROTE " + outpath + " funcs " + funcs.size());
    }
}
