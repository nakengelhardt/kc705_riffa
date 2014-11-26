import sys, operator, functools


from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState

from migen.fhdl import verilog

import riffa, replacementpolicies
from virtmem import VirtmemWrapper

class FSMReg(Module):
	def __init__(self, width):
		self.reg = Signal(width)
		self.reg_n = Signal(width)
		self.reg_en = Signal()
		self.sync += If(self.reg_en, self.reg.eq(self.reg_n))

	def nextval(self, val):
		return (self.reg_n.eq(val), self.reg_en.eq(1))

class Whoosh(VirtmemWrapper):

	def make_fsm_reg(self, name, width):
		setattr(self.submodules, name, FSMReg(width))

	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, drive_clocks=True):
		VirtmemWrapper.__init__(self, combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, wordsize=wordsize, ptrsize=ptrsize, drive_clocks=drive_clocks)

		###
		rx2, tx2 = self.get_channel(2)

		fsm = FSM()
		self.submodules += fsm

		rlen = FSMReg(32)

		rcount = FSMReg(32)
		tcount = FSMReg(32)

		startaddr = FSMReg(ptrsize)
		x_range = FSMReg(32)
		y_range = FSMReg(32)
		xy_range = FSMReg(32)
		current = FSMReg(32)

		array_read_bound = FSMReg(32)
		array_write_bound = FSMReg(32)
		write_adr = FSMReg(64)
		read_adr = FSMReg(64)

		total_pixels = FSMReg(32)

		self.submodules += rlen, rcount, tcount, startaddr, x_range, y_range, xy_range, current, total_pixels, array_read_bound, array_write_bound, write_adr, read_adr

		filtersize = 3
		x = Array([Signal(wordsize, name="x") for i in range(filtersize)])
		x_load = Signal()
		x_next = Signal(wordsize)

		self.sync += If(x_load, x[0].eq(x_next), [x[i].eq(x[i-1]) for i in range(1,filtersize)])
		self.comb += x_next.eq(self.virtmem.data_read), self.virtmem.data_write.eq(functools.reduce(operator.xor, (x[i] for i in range(filtersize)), 0))

		fsm.act("IDLE", #0
			rcount.nextval(0),
			tcount.nextval(0),
			current.nextval(0),
			total_pixels.nextval(0),
			If(rx2.start,
				rlen.nextval(rx2.len),
				NextState("RECEIVE")
			)
		)
		fsm.act("RECEIVE", #1
			rx2.ack.eq(1),
			If(rx2.data_valid,
				rx2.data_ren.eq(1),
				rcount.nextval(rcount.reg + c_pci_data_width//wordsize),
				startaddr.nextval(rx2.data[0:ptrsize]),
				# x_range.nextval(rx2.data[ptrsize:ptrsize+32]),
				# y_range.nextval(rx2.data[ptrsize+32:ptrsize+64]),
				xy_range.nextval(rx2.data[ptrsize:ptrsize+32]),
				NextState("CALC_CONSTANTS")
			)
		)
		fsm.act("CALC_CONSTANTS",
			array_read_bound.nextval(xy_range.reg - 1),
			array_write_bound.nextval(xy_range.reg + filtersize - 2),
			read_adr.nextval(startaddr.reg),
			write_adr.nextval(startaddr.reg),
			NextState("GET_PIXEL")
		)
		fsm.act("GET_PIXEL", #2
			self.virtmem.virt_addr.eq(read_adr.reg),
			self.virtmem.req.eq(1),
			If(self.virtmem.done,
				read_adr.nextval(read_adr.reg + (wordsize//8)),
				self.virtmem.req.eq(0),
				total_pixels.nextval(total_pixels.reg + 1),
				x_load.eq(1),
				If(current.reg >= filtersize - 1,
					NextState("PUT_PIXEL")
				).Else(
					current.nextval(current.reg + 1)
				)
			)
		)
		fsm.act("PUT_PIXEL", #3
			If(current.reg >= filtersize - 1,
				self.virtmem.virt_addr.eq(write_adr.reg),
				self.virtmem.req.eq(1),
				self.virtmem.write_enable.eq(1),
				If(self.virtmem.done,
					write_adr.nextval(write_adr.reg + (wordsize//8)),
					self.virtmem.req.eq(0),
					current.nextval(current.reg + 1),
					If(current.reg < array_read_bound.reg,
						NextState("GET_PIXEL")
					).Elif(current.reg < array_write_bound.reg,
						x_next.eq(x[0]),
						x_load.eq(1)
					).Else(
						If(rcount.reg < rlen.reg,
							NextState("RECEIVE")
						).Else(
							NextState("TRANSMIT")
						)					
					)
				)
			)
		)
		fsm.act("TRANSMIT", #4
			tx2.start.eq(1),
			tx2.len.eq(c_pci_data_width//wordsize),
			tx2.data_valid.eq(1),
			tx2.last.eq(1),
			tx2.data.eq(total_pixels.reg), # send back number of pixels written
			If(tx2.data_ren,
				tcount.nextval(tcount.reg + c_pci_data_width//wordsize),
				NextState("IDLE")
			)
		)


def main():
	c_pci_data_width = 128
	num_chnls = 3
	combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
	combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

	m = Whoosh(combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width)
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