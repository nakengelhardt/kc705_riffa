import random
random.seed(6)

from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import virtmem
import riffa

def generate_data(addr):
	return (addr >> 32) & 0xFFFF | (addr & 0xFFFF)


class TBMemory(Module):
	def __init__(self, cmd_rx, cmd_tx, data_rx, data_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, npagesincache=4, pagesize=4096, init_fn=generate_data):
		self.cmd_rx = cmd_rx
		self.cmd_tx = cmd_tx
		self.data_rx = data_rx
		self.data_tx = data_tx
		self.c_pci_data_width = c_pci_data_width
		self.wordsize = wordsize
		self.ptrsize = ptrsize
		self.npagesincache = npagesincache
		self.pagesize = pagesize
		self.modified = {}
		self.flushack = 0
		self.init_fn = init_fn

	def read_mem(self, addr):
		if addr in self.modified:
			return self.modified[addr]
		else:
			return self.init_fn(addr)

	def gen_simulation(self, selfp):
		ret = []
		while True:
			if selfp.cmd_rx.start :
				cmd = yield from riffa.channel_read(selfp.simulator, self.cmd_rx)
				addr = (cmd[1] << 32) | cmd[0]
				pg_addr = (addr >> log2_int(self.pagesize)) << log2_int(self.pagesize) 
				assert(addr == pg_addr)
				if cmd[2] == 0x6e706e70:
					print("Fetching page " + hex(addr))
					yield from riffa.channel_write(selfp.simulator, self.data_tx, [self.read_mem(i) for i in range(pg_addr,pg_addr+self.pagesize, (self.wordsize//8))])
				if cmd[2] == 0x61B061B0:
					print("Writeback page " + hex(addr))
					if len(ret) < self.pagesize//4:
						print("Incomplete writeback: received only " + str(len(ret)) + " words")
					words = [riffa.pack(x) for x in zip(*[ret[i::self.wordsize//32] for i in range(self.wordsize//32)])]
					print("Modified:")
					for i in range(len(words)):
						if words[i] != self.read_mem(addr+i*(self.wordsize//8)):
							self.modified[addr+i*(self.wordsize//8)] = words[i]
							print(hex(addr+i*(self.wordsize//8)) + ": " + str(words[i]))
					ret = []
				if cmd[2] == 0xD1DF1005:
					self.flushack = 1
					print("Cache finished flushing.")
			elif selfp.data_rx.start:
				ret = yield from riffa.channel_read(selfp.simulator, self.data_rx)
			else:
				yield
					

	gen_simulation.passive = True


class TB(Module):
	def __init__(self):
		self.c_pci_data_width = c_pci_data_width = 128
		self.ptrsize = 64
		self.wordsize = 32
		self.pagesize = 4096
		num_chnls = 2
		combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
		combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

		self.submodules.dut = virtmem.VirtmemWrapper(combined_interface_rx=combined_interface_rx, 
			combined_interface_tx=combined_interface_tx, 
			c_pci_data_width=c_pci_data_width, 
			wordsize=self.wordsize, 
			ptrsize=self.ptrsize, 
			drive_clocks=False)

		self.submodules.channelsplitter = riffa.ChannelSplitter(combined_interface_tx, combined_interface_rx)
		tx0, rx0 = self.channelsplitter.get_channel(0)
		tx1, rx1 = self.channelsplitter.get_channel(1)

		self.submodules.tbmem = TBMemory(tx0, rx0, tx1, rx1, c_pci_data_width=c_pci_data_width, wordsize=self.wordsize, ptrsize=self.ptrsize)


	def generate_random_address(self):
		pages = [0x604000, 0x0, 0x597a000, 0x456000, 0xfffe000, 0x7868000, 0x222000, 0xaa45000]
		pg = random.choice(pages)
		off = random.randrange(0,self.pagesize*8//self.wordsize)
		return pg + off<<log2_int(self.wordsize//8)

	def generate_random_transactions(self, num):
		for i in range(num):
			yield (self.generate_random_address(), random.randint(0,1))


	def gen_simulation(self, selfp):
		for addr, we in self.generate_random_transactions(24):
			selfp.dut.virtmem.virt_addr = addr
			selfp.dut.virtmem.req = 1
			selfp.dut.virtmem.write_enable = we
			if we:
				selfp.dut.virtmem.data_write = generate_data(addr) + 1
			yield
			selfp.dut.virtmem.req = 0
			while not selfp.dut.virtmem.done:
				yield
			if we:
				print("Wrote data " + str(generate_data(addr) + 1) + " to address " + hex(addr))
			else:
				print("Read data " + str(selfp.dut.virtmem.data_read) + " from address " + hex(addr))
		selfp.dut.virtmem.virt_addr = 0
		selfp.dut.virtmem.req = 0
		selfp.dut.virtmem.data_write = 0
		selfp.dut.virtmem.write_enable = 0
		# selfp.dut.virtmem.flush_all = 1
		# yield 2
		# while not selfp.dut.virtmem.done:
		# 	yield

		yield from riffa.channel_write(selfp.simulator, self.tbmem.cmd_tx, [0xF1005])
		while not self.tbmem.flushack:
			yield

		# for i in range(1024):
		# 	a, b, c, d = riffa.unpack(selfp.simulator.rd(self.dut.virtmem.mem, i), 4)
		# 	print("{0:04x}: {1:08x} {2:08x} {3:08x} {4:08x}".format(i*16, a, b, c, d))
		# yield



if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd", ncycles=10000)
