import sys

from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState, NextValue

from migen.sim.generic import run_simulation

from migen.fhdl import verilog

import riffa
from virtmem_tb import TBMemory

class PageTransferrer(Module):
	def __init__(self, rx0, tx0, rx1, tx1, rd_port, wr_port, c_pci_data_width=32, wordsize=32, ptrsize=64, npagesincache=4, pagesize=4096):

		self.cmd_rx = rx0
		self.cmd_tx = tx0
		self.data_rx = rx1
		self.data_tx = tx1

		self.rd_port = rd_port
		self.wr_port = wr_port

		self.virt_addr = Signal(ptrsize)
		self.page_addr = Signal(log2_int(npagesincache))
		self.send_req = Signal()
		self.fetch_req = Signal()
		self.req_complete = Signal()

		##

		# fix start signals
		cmd_rx_start_prev = Signal()
		data_rx_start_prev = Signal()

		self.sync += cmd_rx_start_prev.eq(self.cmd_rx.start), data_rx_start_prev.eq(self.data_rx.start)

		cmd_rx_transaction_requested = Signal()
		data_rx_transaction_requested = Signal()

		cmd_rx_transaction_ack = Signal()
		data_rx_transaction_ack = Signal()

		self.sync += If(cmd_rx_transaction_ack, cmd_rx_transaction_requested.eq(0)).Elif(~cmd_rx_transaction_requested & (self.cmd_rx.start == 1) & (cmd_rx_start_prev == 0), cmd_rx_transaction_requested.eq(1))
		self.sync += If(data_rx_transaction_ack, data_rx_transaction_requested.eq(0)).Elif(~data_rx_transaction_requested & (self.data_rx.start == 1) & (data_rx_start_prev == 0), data_rx_transaction_requested.eq(1))


		# constant definitions
		memorywidth = max(c_pci_data_width, wordsize)
		memorysize = npagesincache*pagesize*8//memorywidth

		pcie_word_adr_nbits = log2_int(memorywidth//32)
		num_tx_off = log2_int(c_pci_data_width//32)

		num_tx_per_word = max(1, wordsize//c_pci_data_width)

		words_per_line = c_pci_data_width//wordsize if c_pci_data_width > wordsize else wordsize//c_pci_data_width

		page_adr_nbits = log2_int(npagesincache)
		line_adr_nbits = log2_int(pagesize*8//memorywidth)
		word_adr_nbits = log2_int(words_per_line)
		byte_adr_nbits = log2_int(wordsize//8)

		word_adr_off = byte_adr_nbits
		line_adr_off = log2_int(memorywidth//8)
		page_tag_off = line_adr_nbits + line_adr_off

		page_tag_nbits = ptrsize - page_tag_off

		# variables

		virt_addr_internal = Signal(ptrsize)
		page_addr_internal = Signal(ptrsize)

		rxcount = Signal(32)
		txcount = Signal(32)
		wordcount = Signal(32)
		rlen = Signal(32)

		# state machine that controls page cache
		fsm = FSM()
		self.submodules += fsm

		fsm.act("IDLE", #0
			#reset internal registers
			NextValue(rxcount, 0),
			NextValue(txcount, 0),
			NextValue(wordcount, 0),
			NextValue(rlen, 0),
			self.req_complete.eq(1),
			If(self.send_req,
				NextValue(virt_addr_internal, self.virt_addr),
				NextValue(page_addr_internal, self.page_addr),
				NextState("TX_DIRTY_PAGE_INIT")
			).Elif(self.fetch_req,
				NextValue(virt_addr_internal, self.virt_addr),
				NextValue(page_addr_internal, self.page_addr),
				NextState("TX_PAGE_FETCH_CMD")
			)
		)

		fsm.act("REQ_COMPLETE",
			self.req_complete.eq(1),
			NextState("IDLE")
		)

		# page send

		fsm.act("TX_DIRTY_PAGE_INIT", #4
			self.data_tx.start.eq(1),
			self.data_tx.len.eq(pagesize//4),
			self.data_tx.last.eq(1),
			NextValue(txcount, c_pci_data_width//32),
			NextValue(wordcount, 0),
			If(self.data_tx.ack,
				rd_port.adr.eq(0),
				rd_port.adr[-page_adr_nbits:].eq(page_addr_internal),
				rd_port.re.eq(1),
				NextState("TX_DIRTY_PAGE")
			)
		)
		fsm.act("TX_DIRTY_PAGE", #5
			self.data_tx.start.eq(1),
			self.data_tx.len.eq(pagesize//4),
			self.data_tx.last.eq(1),
			self.data_tx.data_valid.eq(1),
			self.data_tx.data.eq(rd_port.dat_r)
			if c_pci_data_width >= wordsize else
			[If(i == wordcount[:word_adr_nbits], self.data_tx.data.eq(rd_port.dat_r[i*c_pci_data_width:(i+1)*c_pci_data_width])) for i in range(num_tx_per_word)],
			If(self.data_tx.data_ren,
				NextValue(txcount, txcount + c_pci_data_width//32),
				NextValue(wordcount, wordcount + 1),
				If(txcount < (pagesize//4),
					rd_port.adr[0: line_adr_nbits].eq(txcount[pcie_word_adr_nbits:pcie_word_adr_nbits + line_adr_nbits]),
					rd_port.adr[-page_adr_nbits:].eq(page_addr_internal),
					rd_port.re.eq(1)
				).Else(
					NextState("TX_WRITEBACK_CMD")
				)
			)
		)

		page_writeback_cmd = Signal(128)
		self.comb += page_writeback_cmd[64:128].eq(0x61B061B061B061B0), page_writeback_cmd[page_tag_off:64].eq(virt_addr_internal[page_tag_off:64])
		fsm.act("TX_WRITEBACK_CMD", #2
			self.cmd_tx.start.eq(1),
			self.cmd_tx.len.eq(4),
			self.cmd_tx.last.eq(1),
			If(self.cmd_tx.ack,
				NextState("TX_WRITEBACK_CMD0")
			)
		)
		for i in range(128//c_pci_data_width):
			fsm.act("TX_WRITEBACK_CMD" + str(i), #3
				self.cmd_tx.start.eq(1),
				self.cmd_tx.len.eq(4),
				self.cmd_tx.last.eq(1),
				self.cmd_tx.data.eq(page_writeback_cmd[i*c_pci_data_width:(i+1)*c_pci_data_width]),
				self.cmd_tx.data_valid.eq(1),
				If(self.cmd_tx.data_ren,
					NextState("TX_WRITEBACK_CMD" + str(i+1)) 
					if i+1 < 128//c_pci_data_width else 
					NextState("REQ_COMPLETE")
				)
			)


		# page fetch

		page_fetch_cmd = Signal(128)
		self.comb += page_fetch_cmd[64: 128].eq(0x6E706E706E706E70), page_fetch_cmd[page_tag_off: 64].eq(virt_addr_internal[page_tag_off:])
		fsm.act("TX_PAGE_FETCH_CMD", #6
			self.cmd_tx.start.eq(1),
			self.cmd_tx.len.eq(4),
			self.cmd_tx.last.eq(1),
			If(self.cmd_tx.ack,
				NextState("TX_PAGE_FETCH_CMD0")
			)
		)
		for i in range(128//c_pci_data_width):
			fsm.act("TX_PAGE_FETCH_CMD" + str(i), #7
				self.cmd_tx.start.eq(1),
				self.cmd_tx.len.eq(4),
				self.cmd_tx.last.eq(1),
				self.cmd_tx.data.eq(page_fetch_cmd[i*c_pci_data_width:(i+1)*c_pci_data_width]),
				self.cmd_tx.data_valid.eq(1),
				If(self.cmd_tx.data_ren,
					NextState("TX_PAGE_FETCH_CMD" + str(i+1)) if i+1 < 128//c_pci_data_width else NextState("RX_WAIT")
				)
			)
		fsm.act("RX_WAIT", #8
			NextValue(rxcount, 0),
			If(data_rx_transaction_requested,
				NextValue(rlen, self.data_rx.len),
				NextState("RX_PAGE")
			)
		)
		fsm.act("RX_PAGE", #9
			self.data_rx.ack.eq(1),
			data_rx_transaction_ack.eq(1),
			wr_port.dat_w.eq(Cat([self.data_rx.data for i in range(num_tx_per_word)])),
			wr_port.adr[0:line_adr_nbits].eq(rxcount[pcie_word_adr_nbits: pcie_word_adr_nbits + line_adr_nbits]),
			wr_port.adr[-page_adr_nbits:].eq(page_addr_internal),
			If(self.data_rx.data_valid,
				self.data_rx.data_ren.eq(1),
				[wr_port.we[i].eq(1) for i in range(c_pci_data_width//wordsize)]
				if c_pci_data_width >= wordsize else
				wr_port.we.eq(1 << rxcount[num_tx_off: num_tx_off + word_adr_nbits]),
				NextValue(rxcount, rxcount + c_pci_data_width//32),
				If((rxcount >= (pagesize*8 - c_pci_data_width)//32) | (rxcount >= rlen - c_pci_data_width//32),
					NextState("REQ_COMPLETE")
				)
			)	
		)



class PageTransferrerTB(Module):

	def __init__(self):
		c_pci_data_width = 128
		wordsize = 32
		ptrsize = 64
		npagesincache = 4
		pagesize = 4096

		memorywidth = max(c_pci_data_width, wordsize)
		memorysize = npagesincache*pagesize*8//memorywidth

		self.specials.mem = Memory(memorywidth, memorysize, init=[i+0xABBA for i in range(memorysize)])
		self.specials.rd_port = rd_port = self.mem.get_port(has_re=True)
		self.specials.wr_port = wr_port = self.mem.get_port(write_capable=True, we_granularity=min(wordsize, c_pci_data_width))
		
		num_chnls = 2
		combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
		combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
		self.submodules.channelsplitter = riffa.ChannelSplitter(combined_interface_tx, combined_interface_rx)
		tx0, rx0 = self.channelsplitter.get_channel(0)
		tx1, rx1 = self.channelsplitter.get_channel(1)

		self.submodules.dut = PageTransferrer(rx0, tx0, rx1, tx1, self.rd_port, self.wr_port, c_pci_data_width=c_pci_data_width, wordsize=wordsize, ptrsize=ptrsize, npagesincache=npagesincache, pagesize=pagesize)

		self.submodules.tbmem = TBMemory(tx0, rx0, tx1, rx1, c_pci_data_width=c_pci_data_width)

	def gen_simulation(self, selfp):
		selfp.dut.fetch_req = 1

		selfp.dut.virt_addr = 0x222000
		selfp.dut.page_addr = 0
		yield 2 # req_complete only goes to 0 the cycle after req goes high
		while selfp.dut.req_complete == 0:
			yield

		selfp.dut.virt_addr = 0xbae000
		selfp.dut.page_addr = 1
		yield 2
		while selfp.dut.req_complete == 0:
			yield
		
		selfp.dut.virt_addr = 0xabba000
		selfp.dut.page_addr = 2
		yield 2
		while selfp.dut.req_complete == 0:
			yield
		
		selfp.dut.virt_addr = 0xfaaf000
		selfp.dut.page_addr = 3
		yield 2
		while selfp.dut.req_complete == 0:
			yield

		selfp.dut.fetch_req = 0

		for i in range(1024):
			a, b, c, d = riffa.unpack(selfp.simulator.rd(self.mem, i), 4)
			print("{0:04x}: {1:08x} {2:08x} {3:08x} {4:08x}".format(i*16, a, b, c, d))
		yield

		selfp.dut.send_req = 1

		selfp.dut.virt_addr = 0x222000
		selfp.dut.page_addr = 0
		yield 2
		while selfp.dut.req_complete == 0:
			yield
		
		selfp.dut.virt_addr = 0xbae000
		selfp.dut.page_addr = 1
		yield 2
		while selfp.dut.req_complete == 0:
			yield
		
		selfp.dut.virt_addr = 0xabba000
		selfp.dut.page_addr = 2
		yield 2
		while selfp.dut.req_complete == 0:
			yield
		
		selfp.dut.virt_addr = 0xfaaf000
		selfp.dut.page_addr = 3
		yield 2
		while selfp.dut.req_complete == 0:
			yield

		selfp.dut.send_req = 0

if __name__ == "__main__":
	tb = PageTransferrerTB()
	run_simulation(tb, vcd_name="tb.vcd", keep_files=True, ncycles=30000)