from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import movingaverage
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

		self.submodules.dut = movingaverage.RiffAverage(c_pci_data_width=c_pci_data_width, drive_clocks=False)

		self.submodules.writer = Writer(self.dut.chnl_rx)
		self.submodules.reader = Reader(self.dut.chnl_tx)

		dummy = Signal()
		self.comb += dummy.eq(Cat(self.dut.chnl_rx.raw_bits(), self.dut.chnl_tx.raw_bits()))


if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd")
