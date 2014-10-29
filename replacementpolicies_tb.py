from migen.fhdl.std import *
from migen.sim.generic import run_simulation

from replacementpolicies import *

from random import shuffle

class TB(Module):
	def __init__(self):
		self.npages = 4
		self.submodules.dut = TrueLRU(npages=self.npages)

	def gen_simulation(self, selfp):
		selfp.dut.lru = 135 # 2 0 1 3
		yield
		test_adrs = list(range(16))
		shuffle(test_adrs)
		for i in test_adrs:
			selfp.dut.pg_adr = i % self.npages
			selfp.dut.hit = 1
			print("Hit " + str(i % self.npages))
			yield
			print("LRU: " + str(selfp.dut.pg_to_replace))
			selfp.dut.hit = 0		
			yield
			print("LRU: " + str(selfp.dut.pg_to_replace))
			yield
			print("LRU: " + str(selfp.dut.pg_to_replace))
			yield
			print("LRU: " + str(selfp.dut.pg_to_replace))


if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd", ncycles=5000)