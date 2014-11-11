import sys

from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState

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

		memorysize = npagesincache*pagesize*8//c_pci_data_width

		#virt_addr = [page_tag + line_adr + word_adr + byte_adr]
		#cache_adr = [pg_adr + line_adr]
		page_adr_nbits = log2_int(npagesincache)
		line_adr_nbits = log2_int(pagesize*8//c_pci_data_width)
		word_adr_nbits = log2_int(c_pci_data_width//wordsize)
		byte_adr_nbits = log2_int(wordsize//8)

		word_adr_off = byte_adr_nbits
		line_adr_off = word_adr_nbits + byte_adr_nbits
		page_tag_off = line_adr_nbits + word_adr_nbits + byte_adr_nbits

		page_tag_nbits = ptrsize - page_tag_off

		self.specials.mem = Memory(c_pci_data_width, memorysize, init=[i+1000000 for i in range(memorysize)])
		
		self.specials.rd_port = rd_port = self.mem.get_port(has_re=True)

		self.specials.wr_port = wr_port = self.mem.get_port(write_capable=True, we_granularity=wordsize)
		

		pg_adr = Signal(page_adr_nbits)

		page_tags = Array([Signal(page_tag_nbits, name="page_tags") for i in range(npagesincache)])
		page_tags_n = Array([Signal(page_tag_nbits, name="page_tags_n") for i in range(npagesincache)])
		page_tags_en = Array([Signal(name="page_tags_en") for i in range(npagesincache)])		

		self.sync += [If(page_tags_en[i], page_tags[i].eq(page_tags_n[i])) for i in range(npagesincache)]

		page_valid = Array([Signal(name="page_valid") for i in range(npagesincache)])
		page_valid_n = Array([Signal(name="page_valid_n") for i in range(npagesincache)])
		page_valid_en = Array([Signal(name="page_valid_en") for i in range(npagesincache)])

		self.sync += [If(page_valid_en[i], page_valid[i].eq(page_valid_n[i])) for i in range(npagesincache)]

		page_dirty = Array([Signal(name="page_dirty") for i in range(npagesincache)])
		page_dirty_n = Array([Signal(name="page_dirty_n") for i in range(npagesincache)])
		page_dirty_en = Array([Signal(name="page_dirty_en") for i in range(npagesincache)])

		self.sync += [If(page_dirty_en[i], page_dirty[i].eq(page_dirty_n[i])) for i in range(npagesincache)]

		found = Signal()
		cache_hit_en = Signal()

		self.comb += [If((page_tags[i] == self.virt_addr[page_tag_off:ptrsize]) & page_valid[i], found.eq(1), pg_adr.eq(i)) for i in range(npagesincache)]
		
		self.submodules.replacement_policy = replacementpolicies.TrueLRU(npages=npagesincache)
		pg_to_replace = self.replacement_policy.pg_to_replace
		self.comb += self.replacement_policy.hit.eq(found & cache_hit_en), self.replacement_policy.pg_adr.eq(pg_adr)

		self.make_fsm_reg("rxcount", 32)

		self.make_fsm_reg("tcount", 32)

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
			If(self.req,
				If(found,
					If(self.write_enable,
						NextState("WRITE_DATA")
					).Else(
						cache_hit_en.eq(1),
						rd_port.adr.eq(Cat(self.virt_addr[line_adr_off:line_adr_off + line_adr_nbits], pg_adr)),
						rd_port.re.eq(1),
						self.done_n.eq(1),
						NextState("SERVE_DATA")
					)
				).Else(
					If(page_dirty[pg_to_replace],
						NextState("TX_WRITEBACK_CMD")
					).Else(
						NextState("TX_PAGE_FETCH_CMD")
					)
				)
			).Elif(self.flush_all,
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
				If(self.flush_all, 
					self.done_n.eq(1),
					NextState("IDLE")
				).Else(
					NextState("TX_FLUSH_DONE")
				)
			).Else(
				self.rxcount_n.eq(0),
				self.rxcount_en.eq(1),
				rlen_load.eq(1),
				NextState("TX_WRITEBACK_CMD")
			)
		)
		page_control_fsm.act("TX_WRITEBACK_CMD", #2
			#TODO: this assumes 128b data, make independent
			self.cmd_tx.start.eq(1),
			self.cmd_tx.len.eq((ptrsize + 64)//32),
			self.cmd_tx.data.eq(Cat(zero, page_tags[pg_to_writeback] , 0x61B061B061B061B0)),
			self.cmd_tx.data_valid.eq(1),
			self.cmd_tx.last.eq(1),
			self.tcount_n.eq(0),
			self.tcount_en.eq(1),
			If(self.cmd_tx.data_ren,
				NextState("TX_WAIT")
			)
		)
		page_control_fsm.act("TX_WAIT", #3
			self.data_tx.len.eq(pagesize//4),
			self.data_tx.last.eq(1),
			self.data_tx.start.eq(1),
			If(self.data_tx.ack,
				rd_port.adr.eq(Cat(self.tcount[word_adr_nbits:word_adr_nbits+line_adr_nbits], pg_to_writeback)),
				rd_port.re.eq(1),
				NextState("TX_DIRTY_PAGE")
			)
		)
		page_control_fsm.act("TX_DIRTY_PAGE", #4
			self.data_tx.len.eq(pagesize//4),
			self.data_tx.last.eq(1),
			self.data_tx.data_valid.eq(1),
			self.data_tx.data.eq(rd_port.dat_r),
			If(self.data_tx.data_ren,
				self.tcount_n.eq(self.tcount + c_pci_data_width//32),
				self.tcount_en.eq(1),
				If(self.tcount_n < (pagesize//4),
					rd_port.adr.eq(Cat(self.tcount_n[word_adr_nbits:word_adr_nbits+line_adr_nbits], pg_to_writeback)),
					rd_port.re.eq(1),
					NextState("TX_DIRTY_PAGE")
				).Else(
					page_dirty_n[pg_to_writeback].eq(0),
					page_dirty_en[pg_to_writeback].eq(1),
					If(self.flush_initiated,
						NextState("FLUSH_DIRTY")
					).Else(
						NextState("TX_PAGE_FETCH_CMD")
					)
				)
			)
		)
		page_control_fsm.act("TX_PAGE_FETCH_CMD", #5
			#TODO: this assumes 128b data, make independent
			self.cmd_tx.start.eq(1),
			self.cmd_tx.len.eq((ptrsize + 64)//32),
			self.cmd_tx.data.eq(Cat(zero, self.virt_addr[page_tag_off:] , 0x6E706E706E706E70)),
			self.cmd_tx.data_valid.eq(1),
			self.cmd_tx.last.eq(1),
			If(self.cmd_tx.data_ren,
				NextState("RX_WAIT")
			)
		)
		page_control_fsm.act("RX_WAIT", #6
			self.rxcount_n.eq(0),
			self.rxcount_en.eq(1),
			If(self.data_rx.start,
				rlen_load.eq(1),
				NextState("RX_PAGE")
			)
		)
		page_control_fsm.act("RX_PAGE", #7
			self.data_rx.ack.eq(1),
			wr_port.dat_w.eq(self.data_rx.data),
			wr_port.adr.eq(Cat(self.rxcount[word_adr_nbits:word_adr_nbits+line_adr_nbits], pg_to_replace)),
			If(self.data_rx.data_valid,
				self.data_rx.data_ren.eq(1),
				[wr_port.we[i].eq(1) for i in range(c_pci_data_width//wordsize)],
				self.rxcount_n.eq(self.rxcount + c_pci_data_width//wordsize),
				self.rxcount_en.eq(1),
				If((self.rxcount_n >= pagesize*8//wordsize) | (self.rxcount_n >= rlen),
					page_tags_n[pg_to_replace].eq(self.virt_addr[page_tag_off:ptrsize]),
					page_tags_en[pg_to_replace].eq(1),
					page_valid_n[pg_to_replace].eq(1),
					page_valid_en[pg_to_replace].eq(1),
					If(self.write_enable,
						NextState("WRITE_DATA")
					).Else(
						NextState("GET_DATA")
					)
				)
			)	
		)
		page_control_fsm.act("GET_DATA", #8
			cache_hit_en.eq(1),
			rd_port.adr.eq(Cat(self.virt_addr[line_adr_off:line_adr_off + line_adr_nbits], pg_adr)),
			rd_port.re.eq(1),
			self.done_n.eq(1),
			NextState("SERVE_DATA")
		)
		page_control_fsm.act("SERVE_DATA", #9
			[If(self.virt_addr[word_adr_off:word_adr_off+word_adr_nbits] == i, self.data_read.eq(rd_port.dat_r[i*wordsize:(i+1)*wordsize])) for i in range(c_pci_data_width//wordsize)],
			NextState("IDLE")
		)
		page_control_fsm.act("WRITE_DATA", #10
			cache_hit_en.eq(1),
			wr_port.dat_w.eq(Cat([self.data_write for i in range(c_pci_data_width//wordsize)])),
			wr_port.we.eq(1 << self.virt_addr[word_adr_off:word_adr_off+word_adr_nbits]),
			wr_port.adr.eq(Cat(self.virt_addr[line_adr_off:line_adr_off + line_adr_nbits], pg_adr)),
			page_dirty_n[pg_adr].eq(1),
			page_dirty_en[pg_adr].eq(1),
			self.done_n.eq(1),
			NextState("IDLE")
		)
		page_control_fsm.act("RX_CMD", #11
			self.cmd_rx.ack.eq(1),
			If(self.cmd_rx.data_valid,
				self.cmd_rx.data_ren.eq(1),
				If(self.cmd_rx.data[0:32] == 0xF1005,
					NextState("FLUSH_DIRTY")
				)
			)
		)
		page_control_fsm.act("TX_FLUSH_DONE", #12
		#TODO: this assumes 128b data, make independent
		self.cmd_tx.start.eq(1),
			self.cmd_tx.len.eq((ptrsize + 64)//32),
			self.cmd_tx.data.eq(0xD1DF1005D1DF1005 << 64),
			self.cmd_tx.data_valid.eq(1),
			self.cmd_tx.last.eq(1),
			If(self.cmd_tx.data_ren,
				NextState("IDLE")
			)
		)


class VirtmemWrapper(GenericRiffa):
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, drive_clocks=True):
		GenericRiffa.__init__(self, combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, drive_clocks=drive_clocks)

		if drive_clocks:
			self.clock_domains.cd_sys = ClockDomain()

		rx0, tx0 = self.get_channel(0)
		rx1, tx1 = self.get_channel(1)
		self.submodules.virtmem = Virtmem(rx0, tx0, rx1, tx1, c_pci_data_width=c_pci_data_width, wordsize=wordsize, ptrsize=ptrsize)

