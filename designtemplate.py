from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState

from migen.fhdl import verilog

import riffa, replacementpolicies
from virtmem import VirtmemWrapper

def DesignTemplate(VirtmemWrapper):
	"""Template design for implementing a hardware function that accesses virtual memory via the Virtmem interface.
	This template follows the common pattern of a function that:
		1. receives an argument struct via a RIFFA channel
		2. executes a loop that reads from and writes to virtual memory
		3. returns a result struct (and implied notification that the function has finished executing) via the same RIFFA channel
	"""
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, drive_clocks=True):
		# init the Virtual memory module superclass with the same data sizes
		# drive_clocks: simulation does not support multiple clock regions
		VirtmemWrapper.__init__(self, combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, wordsize=wordsize, ptrsize=ptrsize, drive_clocks=drive_clocks)

		###

		# get a channel for communication of base pointers etc.
		# rx/tx variables
		rx, tx = self.get_channel(2)	
		arg_struct_size = ?? # must be multiple of 32 (pad on SW side if necessary)
		arg_struct = Signal(arg_struct_size)

		res_struct_size = ?? # must be multiple of 32 (pad on SW side if necessary)
		res_struct = Signal(res_struct_size)

		# virtmem access variables
		##TODO: give values to these variables
		read_adr = Signal(ptrsize)
		read_data = Signal(wordsize)
		write_adr = Signal(ptrsize)
		write_data = Signal(wordsize)

		# function variables
		done = Signal() # loop condition

		fsm = FSM()
		self.submodules += fsm
		fsm.act("IDLE", # wait for instruction to start calculating
			If(rx.start,
				NextState("RECEIVE0")
			)
		)
		# receive function arg struct
		for n in range(max(1, arg_struct_size//c_pci_data_width)): 
			fsm.act("RECEIVE" + str(n), 
				rx.ack.eq(1),
				If(rx.data_valid,
					rx.data_ren.eq(1),
					NextValue(arg_struct[n*c_pci_data_width:min((n+1)*c_pci_data_width, arg_struct_size)], rx.data),
					NextState("RECEIVE" + str(n+1))
				)
			)
		fsm.act("RECEIVE" + str(max(1, arg_struct_size//c_pci_data_width)),
			##TODO: break up arg struct into members, pre-loop initializations
			NextState("GET_DATA")
		)

		# execute function loop
		fsm.act("GET_DATA", # read loop data from virtual memory
			self.virtmem.virt_addr.eq(read_adr),
			self.virtmem.req.eq(1),
			self.virtmem.write_enable.eq(0),
			If(self.virtmem.done,
				self.virtmem.req.eq(0),
				NextValue(read_data, self.virtmem.data_read),
				NextState("CALCULATE")
			)
		)
		fsm.act("CALCULATE",
			##TODO: loop body
			NextState("PUT_DATA")
		)
		fsm.act("PUT_DATA", # write loop modifications to virtual memory
			self.virtmem.virt_addr.eq(write_adr),
			self.virtmem.req.eq(1),
			self.virtmem.write_enable.eq(1),
			If(self.virtmem.done,
				self.virtmem.req.eq(0),
				If(~done, # loop
					NextState("GET_DATA")
				).Else( # end function body
					NextState("FLUSH")
				)
			)
		)

		# flush virtmem cache modifications to main memory
		fsm.act("FLUSH",
			self.virtmem.flush_all.eq(1),
			If(self.virtmem.done,
				NextState("TRANSMIT_INIT")
			)
		)
		# send function return struct
		fsm.act("TRANSMIT_INIT", # start transmission
			tx.start.eq(1),
			tx.len.eq(res_struct_size//32),
			tx.last.eq(1),
			If(tx.ack,
				NextState("TRANSMIT0")
			)
		)
		for n in range(max(1, res_struct_size//c_pci_data_width)):
			fsm.act("TRANSMIT" + str(n), # TX
				tx.start.eq(1),
				tx.len.eq(res_struct_size//32),
				tx.last.eq(1),
				tx.data.eq(res_struct[n*c_pci_data_width:min((n+1)*c_pci_data_width, res_struct_size)]),
				If(tx.data_ren,
					NextState("TRANSMIT" + str(n+1))
				)
			)
		fsm.act("TRANSMIT" + str(max(1, res_struct_size//c_pci_data_width)), #transmission finished
			##TODO: reset loop variables
			NextState("IDLE")
		)


def main():
	c_pci_data_width = 128 # PCIe lane width
	ptrsize = 64 # pointer size of the host system, 32 bit or 64 bit
	wordsize = 32 # width of data port to design (any power of 2)
	
	num_chnls = 3 # Virtmem takes 2 channels, add more for direct use
	combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
	combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

	m = DesignTemplate(combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, wordsize=wordsize, ptrsize=ptrsize)
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