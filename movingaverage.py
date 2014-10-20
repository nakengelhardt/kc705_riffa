import sys

from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState

from migen.fhdl import verilog


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
		self.chnl_rx = Signal()
		self.chnl_rx_ack = Signal()
		self.chnl_rx_last = Signal()
		self.chnl_rx_len = Signal(wordsize)
		self.chnl_rx_off = Signal(wordsize-1)
		self.chnl_rx_data = Signal(c_pci_data_width)
		self.chnl_rx_data_valid = Signal()
		self.chnl_rx_data_ren = Signal()

		self.chnl_tx_clk = Signal()
		self.chnl_tx = Signal()
		self.chnl_tx_ack = Signal()
		self.chnl_tx_last = Signal()
		self.chnl_tx_len = Signal(wordsize)
		self.chnl_tx_off = Signal(wordsize-1)
		self.chnl_tx_data = Signal(c_pci_data_width)
		self.chnl_tx_data_valid = Signal()
		self.chnl_tx_data_ren = Signal()

		###

		rlen = Signal(32)
		rcount = Signal(32)
		rcount_n = Signal(32)
		rcount_en = Signal()

		self.sync += If(rcount_en, rcount.eq(rcount_n))

		# avg = MovingAverage(n=firorder,wordsize=wordsize,nsamples=c_pci_data_width//wordsize)
		# self.submodules += avg

		self.comb += self.chnl_tx_last.eq(1), \
			self.chnl_tx_off.eq(0), \
			self.chnl_tx_len.eq(rlen)#, \
			#avg.sample_in.eq(self.chnl_rx_data), \
			#[self.chnl_tx_data[i*wordsize:(i+1)*wordsize].eq(avg.average) for i in range(c_pci_data_width//wordsize)]
		
		if drive_clocks:
			self.clock_domains.cd_sys = ClockDomain()
			self.comb += self.chnl_rx_clk.eq(self.cd_sys.clk), self.chnl_tx_clk.eq(self.cd_sys.clk)

		rlen_load = Signal()
		self.sync += If(rlen_load, rlen.eq(self.chnl_rx_len))

		rdata = Signal(c_pci_data_width)
		self.sync += If(self.chnl_rx_data_valid, rdata.eq(self.chnl_rx_data))

		fsm = FSM()
		self.submodules += fsm



		fsm.act("IDLE",
			If(self.chnl_rx,
				rlen_load.eq(1),
				rcount_n.eq(0),
				rcount_en.eq(1),
				NextState("RECEIVING")
			)
		)
		# self.comb += self.chnl_rx_ack.eq(fsm.after_entering("RECEIVING"))
		fsm.act("RECEIVING",
			self.chnl_rx_ack.eq(1),
			self.chnl_rx_data_ren.eq(1),
			If(self.chnl_rx_data_valid,
				rcount_n.eq(rcount + c_pci_data_width//wordsize),
				rcount_en.eq(1)
				# avg.sample_valid.eq(1),
				
			),
			If(rcount >= rlen,
				NextState("PREPARE_TX")
			)
		)
		fsm.act("PREPARE_TX",
			rcount_n.eq(0),
			rcount_en.eq(1),
			NextState("TRANSMITTING")
		)

		fsm.act("TRANSMITTING",
			self.chnl_tx.eq(1),
			self.chnl_tx_data_valid.eq(1),
			If(self.chnl_tx_data_ren,
				[self.chnl_tx_data[i*wordsize:(i+1)*wordsize].eq(rcount + i + 1) for i in range(c_pci_data_width//wordsize)],
				rcount_n.eq(rcount + c_pci_data_width//wordsize),
				rcount_en.eq(1),
				If(rcount >= rlen, 
					NextState("IDLE")
				)
			)
		)




def main():
	m = RiffAverage(c_pci_data_width=128)
	m.cd_sys.clk.name_override="clk"
	m.cd_sys.rst.name_override="rst"
	print(verilog.convert(m, name="MovingAverage", ios={
		m.chnl_rx_clk,
		m.chnl_rx,
		m.chnl_rx_ack,
		m.chnl_rx_last,
		m.chnl_rx_len,
		m.chnl_rx_off,
		m.chnl_rx_data,
		m.chnl_rx_data_valid,
		m.chnl_rx_data_ren,
		m.chnl_tx_clk,
		m.chnl_tx,
		m.chnl_tx_ack,
		m.chnl_tx_last,
		m.chnl_tx_len,
		m.chnl_tx_off,
		m.chnl_tx_data,
		m.chnl_tx_data_valid,
		m.chnl_tx_data_ren,
		m.cd_sys.clk,
		m.cd_sys.rst}))

if __name__ == '__main__':
	main()