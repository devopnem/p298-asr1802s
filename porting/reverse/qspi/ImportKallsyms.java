// ImportKallsyms.java - Ghidra headless pre-script
// Imports /proc/kallsyms (from the live router) as labels/functions so the
// decompiled QSPI code shows real symbol names. Addresses match the Image
// because Ghidra is loaded at -imagebase 0xc0008000.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.io.*;

public class ImportKallsyms extends GhidraScript {
    public void run() throws Exception {
        String path = (getScriptArgs() != null && getScriptArgs().length > 0)
                ? getScriptArgs()[0] : "/dev/null";
        BufferedReader br = new BufferedReader(new FileReader(path));
        SymbolTable st = currentProgram.getSymbolTable();
        FunctionManager fm = currentProgram.getFunctionManager();
        // Align Ghidra's address space to the kernel load address so kallsyms
        // addresses (0xc0008000-based) map 1:1 onto the raw Image bytes.
        try {
            currentProgram.setImageBase(toAddr(0xc0008000L), false);
        } catch (Exception e) {
            println("setImageBase warn: " + e.getMessage());
        }
        String line;
        int n = 0, nf = 0;
        while ((line = br.readLine()) != null) {
            String t = line.trim();
            if (t.isEmpty()) continue;
            String[] p = t.split("\\s+");
            if (p.length < 3) continue;
            long addr;
            try { addr = Long.parseLong(p[0], 16); } catch (Exception e) { continue; }
            String name = p[2];
            try {
                ghidra.program.model.address.Address a = toAddr(addr);
                st.createLabel(a, name, SourceType.IMPORTED);
                n++;
                if (fm.getFunctionAt(a) != null) nf++;
            } catch (Exception e) { /* skip duplicates/invalid */ }
        }
        println("ImportKallsyms: labels=" + n + " functions=" + nf);
    }
}
