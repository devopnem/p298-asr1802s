/* SPDX-License-Identifier: GPL-2.0 */
#ifndef __DT_BINDINGS_CLOCK_MARVELL_ASR1802S_H
#define __DT_BINDINGS_CLOCK_MARVELL_ASR1802S_H

/*
 * ASR1802S clock identifiers.
 *
 * The CPU FCCR (reg +0x110) carries the PLL mux (sel [0:2]) plus the
 * l2clk / pdclk / baclk divider fields and a GO bit.  These four clocks
 * are therefore one "fccr" clock whose rate is derived from a selectable
 * PLL.  The derived dividers are exposed as separate clocks so that
 * consumers can reference them individually.
 *
 *   0  - PLL0       624 MHz
 *   1  - PLL1       312 MHz
 *   2  - PLL2       416 MHz
 *   3  - PLL4       832 MHz
 *   4  - PLL6      1248 MHz
 *   5  - cpu (pclk)
 *   6  - l2clk       (pclk / (l2div + 1))
 *   7  - pdclk       (pclk / (pddiv + 1))
 *   8  - baclk       (pclk / (baclkdiv + 1))   -> APB domain
 *   9  - periphclk   (pclk, divider register unknown, fixed 1:1 for now)
 *  10  - ddr
 *  11  - axi
 *
 * Cells 12-14 are internal fixed sources consumed only by the driver:
 *   12  - pll_ddr   1066 MHz  (DDR parent)
 *  13  - axi_src0  208 MHz    (AXI parent, sel = 0)
 *  14  - axi_src1  312 MHz    (AXI parent, sel = 1)
 */

#define ASR1802S_CLK_PLL0		0
#define ASR1802S_CLK_PLL1		1
#define ASR1802S_CLK_PLL2		2
#define ASR1802S_CLK_PLL4		3
#define ASR1802S_CLK_PLL6		4
#define ASR1802S_CLK_CPU		5
#define ASR1802S_CLK_L2			6
#define ASR1802S_CLK_PD			7
#define ASR1802S_CLK_BACLK		8
#define ASR1802S_CLK_PERIPH		9
#define ASR1802S_CLK_DDR		10
#define ASR1802S_CLK_AXI		11
#define ASR1802S_CLK_DDR_SRC	12
#define ASR1802S_CLK_AXI_SRC0	13
#define ASR1802S_CLK_AXI_SRC1	14

#define ASR1802S_CLK_NR_CLKS		15

#endif /* __DT_BINDINGS_CLOCK_MARVELL_ASR1802S_H */
