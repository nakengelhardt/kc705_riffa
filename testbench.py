from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import virtmem

c_pci_data_width=128

class TB(Module):
	def __init__(self):
		self.submodules.dut = virtmem.Virtmem(c_pci_data_width=c_pci_data_width, drive_clocks=False)
		

	def gen_simulation(self, selfp):
		selfp.dut.combined_interface_rx.start |= (1 << 0)
		selfp.dut.combined_interface_rx.len = (selfp.dut.combined_interface_rx.len & 0xFFFFFFFF00000000) | (16 << 0)
		selfp.dut.combined_interface_rx.last |= (1 << 0)
		yield
		while not selfp.dut.combined_interface_rx.ack & 0x1:
			yield
		selfp.dut.combined_interface_rx.data_valid |= (1 << 0)
		i = 0
		while i < 16:
			if selfp.dut.combined_interface_rx.data_ren & 0x1:
				i += 1
				selfp.dut.combined_interface_rx.data = (selfp.dut.combined_interface_rx.data & ((2**c_pci_data_width - 1) << c_pci_data_width) ) | ((i + 1) << 0)
			yield

if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd")
