import sys

from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState

from migen.fhdl import verilog

import riffa

class GenericRiffa(Module):
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, num_chnls=1, drive_clocks=True):
		self.combined_interface_tx = combined_interface_tx
		self.combined_interface_rx = combined_interface_rx
		self._max_channels = num_chnls
		self._num_channels = 0
		self.c_pci_data_width = c_pci_data_width
		self.submodules.channelsplitter = riffa.ChannelSplitter(combined_interface_rx, combined_interface_tx)
		if drive_clocks:
			self.rx_clk = Signal(self._max_channels)
			self.tx_clk = Signal(self._max_channels)
			self.comb += [ self.rx_clk[i].eq(ClockSignal()) for i in range(self._max_channels) ]
			self.comb += [ self.tx_clk[i].eq(ClockSignal()) for i in range(self._max_channels) ]


	def get_channel(self, i):
		return self.channelsplitter.get_channel(i)


class Virtmem(Module):
	def __init__(self, rx0, tx0, rx1, tx1, c_pci_data_width=32, wordsize=32, ptrsize=64):
		self.cmd_rx = rx0
		self.cmd_tx = tx0
		self.data_rx = rx1
		self.data_tx = tx1
		self.req = Signal()
		self.virt_addr = Signal(ptrsize)
		self.data = Signal(wordsize)
		self.data_valid = Signal()

		###

		memorysize = 4*4096//c_pci_data_width
		self.specials.mem = Memory(c_pci_data_width, memorysize, init=[i for i in range(memorysize)])
		rd_port = self.mem.get_port(has_re=True, we_granularity=32)
		self.specials.rd_port = rd_port

		self.comb += rd_port.adr.eq(self.virt_addr)

		fsm = FSM()
		self.submodules += fsm

		fsm.act("WAIT_FOR_REQ",
			If(self.req,
				#update lru
				#save virt_addr
				rd_port.re.eq(1),
				#if cache hit
				NextState("SERVE_DATA")
				#else fetch page
			)
		)
		# fsm.act("TX_PAGE_FETCH_CMD",
		# 	self.cmd_tx.start.eq(1),
		# 	self.cmd_tx.len.eq(4),
		# 	self.cmd_tx.data.eq(),
		# 	self.cmd_tx.data_valid.eq(1),
		# 	self.cmd_tx.last.eq(1),
		# 	If(self.cmd_tx.data_ren,
		# 		NextState("RX_PAGE")
		# 	)
		# )
		# fsm.act("RX_PAGE",

		# )
		fsm.act("SERVE_DATA",
			self.data.eq(rd_port.dat_r),
			self.data_valid.eq(1),
			If(~self.req,
				NextState("WAIT_FOR_REQ")
			)
		)

class VirtmemWrapper(GenericRiffa):
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, drive_clocks=True):
		GenericRiffa.__init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=c_pci_data_width, num_chnls=3, drive_clocks=True)

		if drive_clocks:
			self.clock_domains.cd_sys = ClockDomain()

		rx0, tx0 = self.get_channel(0)
		rx1, tx1 = self.get_channel(1)
		rx2, tx2 = self.get_channel(2)
		#self.submodules.virtmem = Virtmem(rx0, tx0, rx1, tx1, c_pci_data_width=32, wordsize=wordsize, ptrsize=ptrsize)

		fsm = FSM()
		self.submodules += fsm

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

		tdata = [Signal(wordsize) for i in range(c_pci_data_width//wordsize)]
		tdata_n = [Signal(wordsize) for i in range(c_pci_data_width//wordsize)]
		tdata_en = [Signal() for i in range(c_pci_data_width//wordsize)]

		self.sync += [If(tdata_en[i], tdata[i].eq(tdata_n[i])) for i in range(c_pci_data_width//wordsize)]


		addrs = [Signal(ptrsize) for i in range(c_pci_data_width//ptrsize)]
		addrs_load = Signal()

		self.sync += [If(addrs_load, addrs[i].eq(rx2.data[i*ptrsize:(i+1)*ptrsize])) for i in range(c_pci_data_width//ptrsize)]

		ndatareq = Signal(32)
		ndatareq_n = Signal(32)
		ndatareq_en = Signal()

		self.sync += If(ndatareq_en, ndatareq.eq(ndatareq_n))

		self.comb += [tx2.data[i*wordsize:(i+1)*wordsize].eq(tdata[i]) for i in range(c_pci_data_width//wordsize)]
		self.comb += tx2.off.eq(0)		

		fsm.act("IDLE",
			rcount_n.eq(0),
			rcount_en.eq(1),
			tcount_n.eq(0),
			tcount_en.eq(1),
			If(rx2.start,
				rlen_load.eq(1),
				NextState("RECEIVE")
			)
		)
		fsm.act("RECEIVE",
			rx2.ack.eq(1),
			If(rx2.data_valid,
				rx2.data_ren.eq(1),
				addrs_load.eq(1),
				rcount_n.eq(rcount + c_pci_data_width//wordsize),
				rcount_en.eq(1),
				ndatareq_n.eq(0),
				ndatareq_en.eq(1),
				# NextState("REQ_DATA")
				[tdata_n[i].eq(i) for i in range(c_pci_data_width//wordsize)],
				[tdata_en[i].eq(1) for i in range(c_pci_data_width//wordsize)],				
				NextState("TRANSMIT")
			)
		)
		fsm.act("REQ_DATA",
			# [If(ndatareq == i, self.virtmem.virt_addr.eq(addrs[i])) for i in range(c_pci_data_width//ptrsize)],
			# self.virtmem.req.eq(1),
			# If(self.virtmem.data_valid,
			# 	self.virtmem.req.eq(0), #deassert as ack
			# 	[tdata_n[i].eq(self.virtmem.data) for i in range(c_pci_data_width//ptrsize)],
			# 	[If(ndatareq == i, tdata_en[i].eq(1)) for i in range(c_pci_data_width//ptrsize)],
			# 	ndatareq_n.eq(ndatareq + 1),
			# 	If(ndatareq_n >= c_pci_data_width//ptrsize,  #TODO: calculate if only 1 at end
			# 		NextState("TRANSMIT")
			# 	)
			# )
		)
		fsm.act("TRANSMIT",
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

	m = VirtmemWrapper(combined_interface_rx, combined_interface_tx, c_pci_data_width=c_pci_data_width)
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
