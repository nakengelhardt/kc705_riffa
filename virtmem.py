import sys

from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState, NextValue

from migen.fhdl import verilog

import riffa, replacementpolicies

class GenericRiffa(Module):
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, drive_clocks=True):
		self.combined_interface_tx = combined_interface_tx
		self.combined_interface_rx = combined_interface_rx
		self.c_pci_data_width = c_pci_data_width
		self.submodules.channelsplitter = riffa.ChannelSplitter(combined_interface_rx, combined_interface_tx)

		num_chnls = flen(combined_interface_rx.start)
		if drive_clocks:
			self.rx_clk = Signal(num_chnls)
			self.tx_clk = Signal(num_chnls)
			self.comb += [ self.rx_clk[i].eq(ClockSignal()) for i in range(num_chnls) ]
			self.comb += [ self.tx_clk[i].eq(ClockSignal()) for i in range(num_chnls) ]


	def get_channel(self, i):
		return self.channelsplitter.get_channel(i)



class Virtmem(Module):
	def make_fsm_reg(self, name, width):
		reg = Signal(width, name=name)
		reg_n = Signal(width, name=name+"_n")
		reg_en = Signal(name=name+"_en")
		setattr(self, name, reg)
		setattr(self, name+"_n", reg_n)
		setattr(self, name+"_en", reg_en)
		self.sync += If(reg_en, reg.eq(reg_n))

	def __init__(self, rx0, tx0, rx1, tx1, c_pci_data_width=32, wordsize=32, ptrsize=64, npagesincache=4, pagesize=4096):
		self.cmd_rx = rx0
		self.cmd_tx = tx0
		self.data_rx = rx1
		self.data_tx = tx1
		self.req = Signal()
		self.virt_addr = Signal(ptrsize)
		self.data_read = Signal(wordsize)
		self.done = Signal()
		self.data_write = Signal(wordsize)
		self.write_enable = Signal()
		self.flush_all = Signal()

		self.done_n = Signal()
		self.sync += self.done.eq(self.done_n)
		###

		#register inputs
		virt_addr_p = Signal(ptrsize)
		req_p = Signal()
		data_write_p = Signal(wordsize)
		write_enable_p = Signal()
		flush_all_p = Signal()

		self.sync += virt_addr_p.eq(self.virt_addr), req_p.eq(self.req), data_write_p.eq(self.data_write), write_enable_p.eq(self.write_enable), flush_all_p.eq(self.flush_all)

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

		self.specials.mem = Memory(memorywidth, memorysize, init=[i+0xABBA for i in range(memorysize)])
		
		self.specials.rd_port = rd_port = self.mem.get_port(has_re=True)

		self.specials.wr_port = wr_port = self.mem.get_port(write_capable=True, we_granularity=min(wordsize, c_pci_data_width))
		

		pg_adr = Signal(page_adr_nbits)

		page_tags = Array(Signal(page_tag_nbits, name="page_tags") for i in range(npagesincache))
		page_tags_n = Array(Signal(page_tag_nbits, name="page_tags_n") for i in range(npagesincache))
		page_tags_en = Array(Signal(name="page_tags_en") for i in range(npagesincache))		

		self.sync += [If(page_tags_en[i], page_tags[i].eq(page_tags_n[i])) for i in range(npagesincache)]

		page_valid = Array(Signal(name="page_valid") for i in range(npagesincache))
		page_valid_n = Array(Signal(name="page_valid_n") for i in range(npagesincache))
		page_valid_en = Array(Signal(name="page_valid_en") for i in range(npagesincache))

		self.sync += [If(page_valid_en[i], page_valid[i].eq(page_valid_n[i])) for i in range(npagesincache)]

		page_dirty = Array(Signal(name="page_dirty") for i in range(npagesincache))
		page_dirty_n = Array(Signal(name="page_dirty_n") for i in range(npagesincache))
		page_dirty_en = Array(Signal(name="page_dirty_en") for i in range(npagesincache))

		self.sync += [If(page_dirty_en[i], page_dirty[i].eq(page_dirty_n[i])) for i in range(npagesincache)]

		found = Signal()
		cache_hit_en = Signal()

		self.comb += [If((page_tags[i] == virt_addr_p[page_tag_off:ptrsize]) & page_valid[i], found.eq(1), pg_adr.eq(i)) for i in range(npagesincache)]
		
		self.submodules.replacement_policy = replacementpolicies.TrueLRU(npages=npagesincache)
		pg_to_replace = self.replacement_policy.pg_to_replace
		self.comb += self.replacement_policy.hit.eq(found & cache_hit_en), self.replacement_policy.pg_adr.eq(pg_adr)

		self.make_fsm_reg("rxcount", 32)

		self.make_fsm_reg("tcount", 32)

		self.wordcount = Signal(32)

		rlen = Signal(32)
		rlen_load = Signal()
		self.sync += If(rlen_load, rlen.eq(self.data_rx.len))

		req_data_adr = Signal(ptrsize)

		page_control_fsm = FSM()
		self.submodules += page_control_fsm

		zero = Signal(page_tag_off)
		self.comb += zero.eq(0)

		self.make_fsm_reg("flush_initiated", 1)

		self.make_fsm_reg("pg_to_flush", page_adr_nbits)

		pg_to_writeback = Signal(page_adr_nbits)

		self.comb += pg_to_writeback.eq(Mux(self.flush_initiated, self.pg_to_flush, pg_to_replace))

		flush_done = Signal()

		page_control_fsm.act("IDLE", #0
			If(req_p,
				If(found,
					If(write_enable_p,
						NextState("WRITE_DATA")
					).Else(
						
						NextState("GET_DATA")
					)
				).Else(
					If(page_dirty[pg_to_replace],
						NextState("TX_DIRTY_PAGE_INIT")
					).Else(
						NextState("TX_PAGE_FETCH_CMD")
					)
				)
			).Elif(flush_all_p,
				NextState("FLUSH_DIRTY")
			).Elif(self.cmd_rx.start,
				rlen_load.eq(1),
				NextState("RX_CMD")
			)
		)
		page_control_fsm.act("FLUSH_DIRTY", #1
			self.flush_initiated_n.eq(1),
			self.flush_initiated_en.eq(1),
			flush_done.eq(1),
			[If(page_dirty[i], self.pg_to_flush_n.eq(i), flush_done.eq(0)) for i in range(npagesincache)],
			self.pg_to_flush_en.eq(1),
			If(flush_done,
				self.flush_initiated_n.eq(0),
				self.flush_initiated_en.eq(1),
				If(flush_all_p, 
					self.done_n.eq(1),
					NextState("IDLE")
				).Else(
					NextState("TX_FLUSH_DONE")
				)
			).Else(
				self.rxcount_n.eq(0),
				self.rxcount_en.eq(1),
				rlen_load.eq(1),
				NextState("TX_DIRTY_PAGE_INIT")
			)
		)
		page_writeback_cmd = Signal(128)
		self.comb += page_writeback_cmd[64:128].eq(0x61B061B061B061B0), page_writeback_cmd[page_tag_off:64].eq(page_tags[pg_to_writeback])
		page_control_fsm.act("TX_WRITEBACK_CMD", #2
			self.cmd_tx.start.eq(1),
			self.cmd_tx.len.eq(4),
			self.cmd_tx.last.eq(1),
			If(self.cmd_tx.ack,
				NextState("TX_WRITEBACK_CMD0")
			)
		)
		for i in range(128//c_pci_data_width):
			page_control_fsm.act("TX_WRITEBACK_CMD" + str(i), #3
				self.cmd_tx.start.eq(1),
				self.cmd_tx.len.eq(4),
				self.cmd_tx.last.eq(1),
				self.cmd_tx.data.eq(page_writeback_cmd[i*c_pci_data_width:(i+1)*c_pci_data_width]),
				self.cmd_tx.data_valid.eq(1),
				If(self.cmd_tx.data_ren,
					NextState("TX_WRITEBACK_CMD" + str(i+1)) 
					if i+1 < 128//c_pci_data_width else 
					(page_dirty_n[pg_to_writeback].eq(0),
					page_dirty_en[pg_to_writeback].eq(1),
					If(self.flush_initiated,
						NextState("FLUSH_DIRTY")
					).Else(
						NextState("TX_PAGE_FETCH_CMD")
					))
				)
			)
		page_control_fsm.act("TX_DIRTY_PAGE_INIT", #4
			self.data_tx.start.eq(1),
			self.data_tx.len.eq(pagesize//4),
			self.data_tx.last.eq(1),
			self.tcount_n.eq(c_pci_data_width//32),
			self.tcount_en.eq(1),
			NextValue(self.wordcount, 0),
			If(self.data_tx.ack,
				rd_port.adr.eq(0),
				rd_port.adr[-page_adr_nbits:].eq(pg_to_writeback),
				rd_port.re.eq(1),
				NextState("TX_DIRTY_PAGE")
			)
		)
		page_control_fsm.act("TX_DIRTY_PAGE", #5
			self.data_tx.start.eq(1),
			self.data_tx.len.eq(pagesize//4),
			self.data_tx.last.eq(1),
			self.data_tx.data_valid.eq(1),
			self.data_tx.data.eq(rd_port.dat_r)
			if c_pci_data_width >= wordsize else
			[If(i == self.wordcount[:word_adr_nbits], self.data_tx.data.eq(rd_port.dat_r[i*c_pci_data_width:(i+1)*c_pci_data_width])) for i in range(num_tx_per_word)],
			If(self.data_tx.data_ren,
				self.tcount_n.eq(self.tcount + c_pci_data_width//32),
				self.tcount_en.eq(1),
				NextValue(self.wordcount, self.wordcount + 1),
				If(self.tcount < (pagesize//4),
					rd_port.adr[0: line_adr_nbits].eq(self.tcount[pcie_word_adr_nbits:pcie_word_adr_nbits + line_adr_nbits]),
					rd_port.adr[-page_adr_nbits:].eq(pg_to_writeback),
					rd_port.re.eq(1),
					NextState("TX_DIRTY_PAGE")
				).Else(
					NextState("TX_WRITEBACK_CMD")
				)
			)
		)
		page_fetch_cmd = Signal(128)
		self.comb += page_fetch_cmd[64: 128].eq(0x6E706E706E706E70), page_fetch_cmd[page_tag_off: 64].eq(virt_addr_p[page_tag_off:])
		page_control_fsm.act("TX_PAGE_FETCH_CMD", #6
			self.cmd_tx.start.eq(1),
			self.cmd_tx.len.eq(4),
			self.cmd_tx.last.eq(1),
			If(self.cmd_tx.ack,
				NextState("TX_PAGE_FETCH_CMD0")
			)
		)
		for i in range(128//c_pci_data_width):
			page_control_fsm.act("TX_PAGE_FETCH_CMD" + str(i), #7
				self.cmd_tx.start.eq(1),
				self.cmd_tx.len.eq(4),
				self.cmd_tx.last.eq(1),
				self.cmd_tx.data.eq(page_fetch_cmd[i*c_pci_data_width:(i+1)*c_pci_data_width]),
				self.cmd_tx.data_valid.eq(1),
				If(self.cmd_tx.data_ren,
					NextState("TX_PAGE_FETCH_CMD" + str(i+1)) if i+1 < 128//c_pci_data_width else NextState("RX_WAIT")
				)
			)
		page_control_fsm.act("RX_WAIT", #8
			self.rxcount_n.eq(0),
			self.rxcount_en.eq(1),
			If(self.data_rx.start,
				rlen_load.eq(1),
				NextState("RX_PAGE")
			)
		)
		page_control_fsm.act("RX_PAGE", #9
			self.data_rx.ack.eq(1),
			wr_port.dat_w.eq(Cat([self.data_rx.data for i in range(num_tx_per_word)])),
			wr_port.adr[0:line_adr_nbits].eq(self.rxcount[pcie_word_adr_nbits: pcie_word_adr_nbits + line_adr_nbits]),
			wr_port.adr[-page_adr_nbits:].eq(pg_to_replace),
			If(self.data_rx.data_valid,
				self.data_rx.data_ren.eq(1),
				[wr_port.we[i].eq(1) for i in range(c_pci_data_width//wordsize)]
				if c_pci_data_width >= wordsize else
				wr_port.we.eq(1 << self.rxcount[num_tx_off: num_tx_off + word_adr_nbits]),
				self.rxcount_n.eq(self.rxcount + c_pci_data_width//32),
				self.rxcount_en.eq(1),
				If((self.rxcount >= (pagesize*8 - c_pci_data_width)//32) | (self.rxcount >= rlen - c_pci_data_width//32),
					page_tags_n[pg_to_replace].eq(virt_addr_p[page_tag_off: ptrsize]),
					page_tags_en[pg_to_replace].eq(1),
					page_valid_n[pg_to_replace].eq(1),
					page_valid_en[pg_to_replace].eq(1),
					If(write_enable_p,
						NextState("WRITE_DATA")
					).Else(
						NextState("GET_DATA")
					)
				)
			)	
		)
		page_control_fsm.act("GET_DATA", #10
			cache_hit_en.eq(1),
			rd_port.adr.eq(Cat(virt_addr_p[line_adr_off:line_adr_off + line_adr_nbits], pg_adr)),
			rd_port.re.eq(1),
			self.done_n.eq(1),
			NextState("SERVE_DATA")
		)
		page_control_fsm.act("SERVE_DATA", #11
			[If(virt_addr_p[word_adr_off:word_adr_off+word_adr_nbits] == i, self.data_read.eq(rd_port.dat_r[i*wordsize:(i+1)*wordsize])) for i in range(c_pci_data_width//wordsize)]
			if c_pci_data_width > wordsize else
			self.data_read.eq(rd_port.dat_r),
			NextState("WAIT_1")
		)
		page_control_fsm.act("WRITE_DATA", #12
			cache_hit_en.eq(1),
			wr_port.dat_w.eq(Cat([data_write_p for i in range(words_per_line)]))
			if c_pci_data_width > wordsize else
			wr_port.dat_w.eq(data_write_p),
			wr_port.we.eq(1 << virt_addr_p[word_adr_off:word_adr_off+word_adr_nbits])
			if c_pci_data_width > wordsize else
			[wr_port.we[i].eq(1) for i in range(words_per_line)],
			wr_port.adr.eq(Cat(virt_addr_p[line_adr_off:line_adr_off + line_adr_nbits], pg_adr)),
			page_dirty_n[pg_adr].eq(1),
			page_dirty_en[pg_adr].eq(1),
			self.done_n.eq(1),
			NextState("WAIT_1")
		)
		page_control_fsm.act("RX_CMD", #13
			self.cmd_rx.ack.eq(1),
			If(self.cmd_rx.data_valid,
				self.cmd_rx.data_ren.eq(1),
				If(self.cmd_rx.data[0:32] == 0xF1005,
					NextState("FLUSH_DIRTY")
				)
			)
		)
		flush_done_cmd = Signal(128)
		self.comb += flush_done_cmd[64:128].eq(0xD1DF1005D1DF1005)
		page_control_fsm.act("TX_FLUSH_DONE", #14
			self.cmd_tx.start.eq(1),
			self.cmd_tx.len.eq(4),
			self.cmd_tx.last.eq(1),
			If(self.cmd_tx.ack,
				NextState("TX_FLUSH_DONE0")
			)
		)
		for i in range(128//c_pci_data_width):
			page_control_fsm.act("TX_FLUSH_DONE" + str(i), #15
				self.cmd_tx.start.eq(1),
				self.cmd_tx.len.eq(4),
				self.cmd_tx.last.eq(1),
				self.cmd_tx.data.eq(flush_done_cmd[i*c_pci_data_width:(i+1)*c_pci_data_width]),
				self.cmd_tx.data_valid.eq(1),
				If(self.cmd_tx.data_ren,
					NextState("TX_FLUSH_DONE" + str(i+1)) if i+1 < 128//c_pci_data_width else NextState("IDLE")
				)
			)
		page_control_fsm.act("WAIT_1", #16
			NextState("IDLE")
		)


class VirtmemWrapper(GenericRiffa):
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, drive_clocks=True):
		GenericRiffa.__init__(self, combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, drive_clocks=drive_clocks)

		if drive_clocks:
			self.clock_domains.cd_sys = ClockDomain()

		rx0, tx0 = self.get_channel(0)
		rx1, tx1 = self.get_channel(1)
		self.submodules.virtmem = Virtmem(rx0, tx0, rx1, tx1, c_pci_data_width=c_pci_data_width, wordsize=wordsize, ptrsize=ptrsize)

