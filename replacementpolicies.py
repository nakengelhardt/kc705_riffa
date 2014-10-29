from migen.fhdl.std import *

from migen.fhdl import verilog

import itertools

class TrueLRU(Module):
	def __init__(self, npages=4):
		self.hit = hit = Signal()
		self.pg_adr = pg_adr = Signal(log2_int(npages))
		self.pg_to_replace = pg_to_replace = Signal(log2_int(npages))
		self.npages = npages

		rom_contents = [0x1B for i in range(2**((npages+1)*log2_int(npages)))]

		for state in itertools.permutations(range(npages)):
			for page in range(npages):
				addr = page
				for s in state:
					addr = (addr << log2_int(npages)) | s
				next_state = list(state)
				next_state.remove(page)
				next_state.insert(0, page)
				next_state_int = 0
				for s in next_state:
					next_state_int = (next_state_int << log2_int(npages)) | s
				rom_contents[addr] = next_state_int

		rom = Array(rom_contents)

		self.lru = lru = Signal(npages*log2_int(npages))
		lru_addr = Signal((npages+1)*log2_int(npages))

		self.comb += lru_addr.eq(Cat(lru, pg_adr))
		self.sync += If(hit, lru.eq(rom[lru_addr]))

		self.comb += pg_to_replace.eq(lru[0:log2_int(npages)])


# class PseudoLRU(Module):
# 	def __init__(self, npages=4):
# 		self.hit = hit = Signal()
# 		self.pg_adr = pg_adr = Signal(log2_int(npages))
# 		self.pg_to_replace = pg_to_replace = Signal(log2_int(npages))
# 		self.npages = npages

# 		lru = Array([Array([Signal() for x in range(i+1)]) for i in range(log2_int(npages))])
# 		lru_addr = Array([Signal()] + [Signal(i) for i in range(1,log2_int(npages)+1)])

# 		self.comb += lru_addr[0].eq(0), lru_addr[1].eq(lru[0][lru_addr[0]])
# 		for i in range(2, log2_int(npages) + 1):
# 			self.comb += lru_addr[i].eq(Cat(lru[i-1][lru_addr[i-1]], lru_addr[i-1]))
# 		self.comb += pg_to_replace.eq(lru_addr[-1])

# 		self.sync += If(hit, lru[0][0].eq(~pg_adr[-1])), [If(hit, lru[i][pg_adr[0:i]].eq(~pg_adr[-(i+1):])) for i in range(1, log2_int(npages))]


def main():
	plru = TrueLRU()
	print(verilog.convert(plru, ios={plru.hit, plru.pg_adr, plru.pg_to_replace}))

if __name__ == '__main__':
	main()