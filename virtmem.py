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
	def __init__(self, rx0, tx0, rx1, tx1, c_pci_data_width=32, wordsize=32, ptrsize=64, npagesincache=4, pagesize=4096):
		self.cmd_rx = rx0
		self.cmd_tx = tx0
		self.data_rx = rx1
		self.data_tx = tx1
		self.req = Signal()
		self.virt_addr = Signal(ptrsize)
		self.data = Signal(wordsize)
		self.data_valid = Signal()

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
		page_tags_en = Array([Signal(page_tag_nbits, name="page_tags_en") for i in range(npagesincache)])		

		self.sync += [If(page_tags_en[i], page_tags[i].eq(page_tags_n[i])) for i in range(npagesincache)]

		page_valid = Array([Signal(name="page_valid") for i in range(npagesincache)])
		page_valid_n = Array([Signal(name="page_valid_n") for i in range(npagesincache)])
		page_valid_en = Array([Signal(name="page_valid_en") for i in range(npagesincache)])

		self.sync += [If(page_valid_en[i], page_valid[i].eq(page_valid_n[i])) for i in range(npagesincache)]

		found = Signal()
		cache_hit_en = Signal()

		self.comb += [If((page_tags[i] == self.virt_addr[page_tag_off:ptrsize]) & page_valid[i], found.eq(1), pg_adr.eq(i)) for i in range(npagesincache)]
		
		self.submodules.replacement_policy = replacementpolicies.TrueLRU(npages=npagesincache)
		pg_to_replace = self.replacement_policy.pg_to_replace
		self.comb += self.replacement_policy.hit.eq(found & cache_hit_en), self.replacement_policy.pg_adr.eq(pg_adr)

		rxcount = Signal(32)
		rxcount_n = Signal(32)
		rxcount_en = Signal()
		self.sync += If(rxcount_en, rxcount.eq(rxcount_n))

		rlen = Signal(32)
		rlen_load = Signal()
		self.sync += If(rlen_load, rlen.eq(self.data_rx.len))

		req_data_adr = Signal(ptrsize)

		page_control_fsm = FSM()
		self.submodules += page_control_fsm

		zero = Signal(page_tag_off)
		self.comb += zero.eq(0)

		page_control_fsm.act("WAIT_FOR_REQ",
			If(self.req,
				#update lru
				#save virt_addr
				If(found,
					cache_hit_en.eq(1),
						rd_port.adr.eq(Cat(self.virt_addr[line_adr_off:line_adr_off + line_adr_nbits], pg_adr)),
						rd_port.re.eq(1),
					NextState("SERVE_DATA")
				).Else(
					NextState("TX_PAGE_FETCH_CMD")
				)
			)
		)
		page_control_fsm.act("TX_PAGE_FETCH_CMD",
			self.cmd_tx.start.eq(1),
			self.cmd_tx.len.eq(4),
			self.cmd_tx.data.eq(Cat(zero, self.virt_addr[page_tag_off:] , 0x6E706E706E706E70)),
			self.cmd_tx.data_valid.eq(1),
			self.cmd_tx.last.eq(1),
			If(self.cmd_tx.data_ren,
				NextState("RX_WAIT")
			)
		)
		page_control_fsm.act("RX_WAIT",
			rxcount_n.eq(0),
			rxcount_en.eq(1),
			If(self.data_rx.start,
				rlen_load.eq(1),
				NextState("RX_PAGE")
			)
		)
		page_control_fsm.act("RX_PAGE",
			self.data_rx.ack.eq(1),
			wr_port.dat_w.eq(self.data_rx.data),
			wr_port.adr.eq(Cat(rxcount[word_adr_nbits:word_adr_nbits+line_adr_nbits], pg_to_replace)),
			If(self.data_rx.data_valid,
				self.data_rx.data_ren.eq(1),
				[wr_port.we[i].eq(1) for i in range(c_pci_data_width//wordsize)],
				rxcount_n.eq(rxcount + c_pci_data_width//wordsize),
				rxcount_en.eq(1),
				If((rxcount_n >= pagesize*8//wordsize) | (rxcount_n >= rlen),
					page_tags_n[pg_to_replace].eq(self.virt_addr[page_tag_off:ptrsize]),
					page_tags_en[pg_to_replace].eq(1),
					page_valid_n[pg_to_replace].eq(1),
					page_valid_en[pg_to_replace].eq(1),
					NextState("GET_DATA")
				)
			)	
		)
		page_control_fsm.act("GET_DATA",
			cache_hit_en.eq(1),
			rd_port.adr.eq(Cat(self.virt_addr[line_adr_off:line_adr_off + line_adr_nbits], pg_adr)),
			rd_port.re.eq(1),
			NextState("SERVE_DATA")
		)
		page_control_fsm.act("SERVE_DATA",
			[If(self.virt_addr[word_adr_off:word_adr_off+word_adr_nbits] == i, self.data.eq(rd_port.dat_r[i*wordsize:(i+1)*wordsize])) for i in range(c_pci_data_width//wordsize)],
			self.data_valid.eq(1),
			NextState("WAIT_FOR_REQ")
		)

class VirtmemWrapper(GenericRiffa):
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, drive_clocks=True):
		GenericRiffa.__init__(self, combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, drive_clocks=drive_clocks)

		if drive_clocks:
			self.clock_domains.cd_sys = ClockDomain()

		rx0, tx0 = self.get_channel(0)
		rx1, tx1 = self.get_channel(1)
		self.submodules.virtmem = Virtmem(rx0, tx0, rx1, tx1, c_pci_data_width=c_pci_data_width, wordsize=wordsize, ptrsize=ptrsize)


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

		self.sync += [If(tdata_load[i], tdata[i].eq(self.virtmem.data)) for i in range(c_pci_data_width//wordsize)]


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
			If(self.virtmem.data_valid,
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
