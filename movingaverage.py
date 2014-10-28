import sys

from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState

from migen.fhdl import verilog

import riffa

# class MovingAverage(Module):
# 	def __init__(self,n=7,wordsize=32,nsamples=1):
# 		self.sample_in = Signal(wordsize * nsamples)
# 		self.sample_valid = Signal()
# 		self.average = Signal(wordsize)

# 		###

# 		self.n = n # must be of form 2^i-1 for int i>=0

# 		self.samples = [Signal(wordsize) for i in range(self.n+1)]
# 		self.sync += If(self.sample_valid, [self.samples[i].eq(self.sample_in[i*wordsize:(i+1)*wordsize]) for i in range(nsamples)], [self.samples[i].eq(self.samples[i-nsamples]) for i in range(nsamples,self.n+1)])
# 		self.sync += self.average.eq(sum(self.samples[i] >> int.bit_length(self.n) for i in range(self.n+1)))

# module chnl_tester #(
# 	parameter C_PCI_DATA_WIDTH = 9'd32
# )
# (
# 	input CLK,
# 	input RST,
# 	output CHNL_RX_CLK, 
# 	input CHNL_RX, 
# 	output CHNL_RX_ACK, 
# 	input CHNL_RX_LAST, 
# 	input [31:0] CHNL_RX_LEN, 
# 	input [30:0] CHNL_RX_OFF, 
# 	input [C_PCI_DATA_WIDTH-1:0] CHNL_RX_DATA, 
# 	input CHNL_RX_DATA_VALID, 
# 	output CHNL_RX_DATA_REN,
	
# 	output CHNL_TX_CLK, 
# 	output CHNL_TX, 
# 	input CHNL_TX_ACK, 
# 	output CHNL_TX_LAST, 
# 	output [31:0] CHNL_TX_LEN, 
# 	output [30:0] CHNL_TX_OFF, 
# 	output [C_PCI_DATA_WIDTH-1:0] CHNL_TX_DATA, 
# 	output CHNL_TX_DATA_VALID, 
# 	input CHNL_TX_DATA_REN
# );

class RiffAverage(Module):
	def __init__(self, c_pci_data_width=32, drive_clocks=True):
		firorder = 7
		wordsize = 32
		self.chnl_rx_clk = Signal()
		self.chnl_tx_clk = Signal()

		self.chnl_rx = riffa.Interface(data_width=c_pci_data_width)
		self.chnl_tx = riffa.Interface(data_width=c_pci_data_width)

		###

		if drive_clocks:
			self.clock_domains.cd_sys = ClockDomain()
			self.comb += self.chnl_rx_clk.eq(self.cd_sys.clk), self.chnl_tx_clk.eq(self.cd_sys.clk)
		
		rcount = Signal(32)
		rcount_n = Signal(32)
		rcount_en = Signal()

		self.sync += If(rcount_en, rcount.eq(rcount_n))

		tcount = Signal(32)
		tcount_n = Signal(32)
		tcount_en = Signal()

		self.sync += If(tcount_en, tcount.eq(tcount_n))

		rlen = Signal(32)
		rlen_load = Signal()
		self.sync += If(rlen_load, rlen.eq(self.chnl_rx.len))

		rdata = Signal(c_pci_data_width)
		self.sync += If(self.chnl_rx.data_valid, rdata.eq(self.chnl_rx.data))

		fsm = FSM()
		self.submodules += fsm

		self.comb += self.chnl_tx.off.eq(0)

		fsm.act("IDLE",
			rcount_n.eq(0),
			rcount_en.eq(1),
			tcount_n.eq(0),
			tcount_en.eq(1),
			If(self.chnl_rx.start,
				rlen_load.eq(1),
				NextState("RECEIVING")
			)
		)
		fsm.act("RECEIVING",
			self.chnl_rx.ack.eq(1),
			If(self.chnl_rx.data_valid,
				rcount_n.eq(rcount + c_pci_data_width//wordsize),
				rcount_en.eq(1),
				self.chnl_rx.data_ren.eq(1),
				NextState("TRANSMITTING")
			),
		)
		fsm.act("TRANSMITTING",
			#TODO: next test, split in 2 transactions of half length
			self.chnl_tx.start.eq(1),
			[self.chnl_tx.data[i*wordsize:(i+1)*wordsize].eq(tcount + i + 1) for i in range(c_pci_data_width//wordsize)],
			self.chnl_tx.len.eq(c_pci_data_width//wordsize), #TODO: calculate if only 1 at end
			self.chnl_tx.data_valid.eq(1),
			self.chnl_tx.last.eq(1),
			If(self.chnl_tx.data_ren,
				tcount_n.eq(tcount + c_pci_data_width//wordsize),
				tcount_en.eq(1),
				If(tcount >= rlen, 
					NextState("IDLE")
				).Else(
					NextState("RECEIVING")
				)
			)
		)




def main():
	m = RiffAverage(c_pci_data_width=128)
	m.cd_sys.clk.name_override="clk"
	m.cd_sys.rst.name_override="rst"
	for name in "ack", "last", "len", "off", "data", "data_valid", "data_ren":
		getattr(m.chnl_rx, name).name_override="chnl_rx_{}".format(name)
		getattr(m.chnl_tx, name).name_override="chnl_tx_{}".format(name)
	m.chnl_rx.start.name_override="chnl_rx"
	m.chnl_tx.start.name_override="chnl_tx"

	print(verilog.convert(m, name="top", ios={
		m.chnl_rx_clk,
		m.chnl_rx.start,
		m.chnl_rx.ack,
		m.chnl_rx.last,
		m.chnl_rx.len,
		m.chnl_rx.off,
		m.chnl_rx.data,
		m.chnl_rx.data_valid,
		m.chnl_rx.data_ren,
		m.chnl_tx_clk,
		m.chnl_tx.start,
		m.chnl_tx.ack,
		m.chnl_tx.last,
		m.chnl_tx.len,
		m.chnl_tx.off,
		m.chnl_tx.data,
		m.chnl_tx.data_valid,
		m.chnl_tx.data_ren,
		m.cd_sys.clk,
		m.cd_sys.rst}))

if __name__ == '__main__':
	main()
