from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import virtmem
import riffa

class Writer(Module):
	def __init__(self, channel):
		self.channel = channel

	def gen_simulation(self, selfp):
		yield from riffa.channel_write(selfp.simulator, self.channel, [i+1337 for i in range(4)])
		yield
		yield
		yield

class Reader(Module):
	def __init__(self, channel):
		self.channel = channel

	def gen_simulation(self, selfp):
		while True:
			words = yield from riffa.channel_read(selfp.simulator, self.channel)
			for word in words:
				print("{0:032x}".format(word))
	gen_simulation.passive = True

class TB(Module):
	def __init__(self):
		c_pci_data_width = 128
		num_chnls = 3
		combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
		combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

		self.submodules.dut = virtmem.VirtmemWrapper(combined_interface_rx, combined_interface_tx, c_pci_data_width=c_pci_data_width, drive_clocks=False)

		self.submodules.channelsplitter = riffa.ChannelSplitter(combined_interface_tx, combined_interface_rx)
		tx, rx = self.channelsplitter.get_channel(2)
		self.submodules.writer = Writer(rx)
		self.submodules.reader = Reader(tx)


if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd")
