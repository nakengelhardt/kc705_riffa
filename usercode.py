import sys

from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState

from migen.fhdl import verilog

import riffa, replacementpolicies
from virtmem import VirtmemWrapper

class UserCode(VirtmemWrapper):
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, drive_clocks=True):
		VirtmemWrapper.__init__(self, combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, wordsize=wordsize, ptrsize=ptrsize, drive_clocks=drive_clocks)

		###
		rx2, tx2 = self.get_channel(2)

		debug_channel_fsm = FSM()
		self.submodules += debug_channel_fsm

		rlen = Signal(32)
		rlen_load = Signal()

		self.sync += If(rlen_load, rlen.eq(rx2.len))

		rcount = Signal(32)
		rcount_n = Signal(32)
		rcount_en = Signal()

		self.sync += If(rcount_en, rcount.eq(rcount_n))

		tcount = Signal(32)
		tcount_n = Signal(32)
		tcount_en = Signal()

		self.sync += If(tcount_en, tcount.eq(tcount_n))

		rdata = Signal(c_pci_data_width)
		rdata_n = Signal(c_pci_data_width)
		rdata_en = Signal()

		self.sync += If(rdata_en, rdata.eq(rdata_n))

		tdata = Array([Signal(wordsize) for i in range(c_pci_data_width//wordsize)])
		tdata_load = Array([Signal() for i in range(c_pci_data_width//wordsize)])

		self.sync += [If(tdata_load[i], tdata[i].eq(self.virtmem.data_read)) for i in range(c_pci_data_width//wordsize)]


		addrs = [Signal(ptrsize) for i in range(c_pci_data_width//ptrsize)]
		addrs_load = Signal()

		self.sync += [If(addrs_load, addrs[i].eq(rx2.data[i*ptrsize:(i+1)*ptrsize])) for i in range(c_pci_data_width//ptrsize)]

		ndatareq = Signal(32)
		ndatareq_n = Signal(32)
		ndatareq_en = Signal()

		self.sync += If(ndatareq_en, ndatareq.eq(ndatareq_n))

		self.comb += [tx2.data[i*wordsize:(i+1)*wordsize].eq(tdata[i]) for i in range(c_pci_data_width//wordsize)]
		self.comb += tx2.off.eq(0)		

		debug_channel_fsm.act("IDLE",
			rcount_n.eq(0),
			rcount_en.eq(1),
			tcount_n.eq(0),
			tcount_en.eq(1),
			If(rx2.start,
				rlen_load.eq(1),
				NextState("RECEIVE")
			)
		)
		debug_channel_fsm.act("RECEIVE",
			rx2.ack.eq(1),
			If(rx2.data_valid,
				rx2.data_ren.eq(1),
				addrs_load.eq(1),
				rcount_n.eq(rcount + c_pci_data_width//wordsize),
				rcount_en.eq(1),
				ndatareq_n.eq(0),
				ndatareq_en.eq(1),
				NextState("REQ_DATA")
				# [tdata_n[i].eq(1) for i in range(c_pci_data_width//wordsize)],
				# [tdata_load[i].eq(1) for i in range(c_pci_data_width//wordsize)],				
				# NextState("TRANSMIT")
			)
		)
		debug_channel_fsm.act("REQ_DATA",
			[If(ndatareq == i, self.virtmem.virt_addr.eq(addrs[i])) for i in range(c_pci_data_width//ptrsize)],
			self.virtmem.req.eq(1),
			If(self.virtmem.done,
				self.virtmem.req.eq(0), #deassert so 
				tdata_load[ndatareq].eq(1),
				ndatareq_n.eq(ndatareq + 1),
				ndatareq_en.eq(1),
				If(ndatareq_n >= c_pci_data_width//ptrsize,  #TODO: calculate if only 1 at end
					NextState("TRANSMIT")
				)
			)
		)
		debug_channel_fsm.act("TRANSMIT",
			tx2.start.eq(1),
			tx2.len.eq(c_pci_data_width//wordsize),
			tx2.data_valid.eq(1),
			tx2.last.eq(1),
			If(tx2.data_ren,
				tcount_n.eq(tcount + c_pci_data_width//wordsize),
				tcount_en.eq(1),
				If(tcount < rlen,
					NextState("RECEIVE")
				).Else(
					NextState("IDLE")
				)
			)
		)


def main():
	c_pci_data_width = 128
	num_chnls = 3
	combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
	combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

	m = UserCode(combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width)
	m.cd_sys.clk.name_override="clk"
	m.cd_sys.rst.name_override="rst"
	for name in "ack", "last", "len", "off", "data", "data_valid", "data_ren":
		getattr(combined_interface_rx, name).name_override="chnl_rx_{}".format(name)
		getattr(combined_interface_tx, name).name_override="chnl_tx_{}".format(name)
	combined_interface_rx.start.name_override="chnl_rx"
	combined_interface_tx.start.name_override="chnl_tx"
	m.rx_clk.name_override="chnl_rx_clk"
	m.tx_clk.name_override="chnl_tx_clk"
	print(verilog.convert(m, name="top", ios={getattr(combined_interface_rx, name) for name in ["start", "ack", "last", "len", "off", "data", "data_valid", "data_ren"]} | {getattr(combined_interface_tx, name) for name in ["start", "ack", "last", "len", "off", "data", "data_valid", "data_ren"]} | {m.rx_clk, m.tx_clk, m.cd_sys.clk, m.cd_sys.rst} ))

if __name__ == '__main__':
	main()