from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import riffa

class Writer(Module):
	def __init__(self, channel):
		self.channel = channel

	def gen_simulation(self, selfp):
		yield from riffa.channel_write(selfp.simulator, self.channel, [i+1337 for i in range(17)])
		yield
		yield
		yield

class Reader(Module):
	def __init__(self, channel):
		self.channel = channel

	def gen_simulation(self, selfp):
		while True:
			words = yield from riffa.channel_read(selfp.simulator, self.channel)
			print(words)
	gen_simulation.passive = True


class RiffaTB(Module):
	def __init__(self):
		channel = riffa.Interface(data_width=128)
		dummy = Signal()
		self.comb += dummy.eq(channel.raw_bits())
		self.submodules.writer = Writer(channel)
		self.submodules.reader = Reader(channel)

if __name__ == "__main__":
	tb = RiffaTB()
	run_simulation(tb, vcd_name="tb.vcd")
