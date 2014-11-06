from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import virtmem
import riffa

def generate_data(addr):
	return (addr >> 32) & 0xFFFF | (addr & 0xFFFF)


class TBMemory(Module):
	def __init__(self, cmd_rx, cmd_tx, data_rx, data_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, npagesincache=4, pagesize=4096):
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

	def read_mem(self, addr):
		if addr in self.modified:
			return self.modified[addr]
		else:
			return generate_data(addr)

	def gen_simulation(self, selfp):
		while True:
			cmd = yield from riffa.channel_read(selfp.simulator, self.cmd_rx)
			addr = (cmd[1] << 32) | cmd[0]
			pg_addr = (addr >> log2_int(self.pagesize)) << log2_int(self.pagesize) 
			assert(addr == pg_addr)
			if cmd[2] == 0x6e706e70:
				print("Fetching page " + hex(addr))
				yield from riffa.channel_write(selfp.simulator, self.data_tx, [self.read_mem(i) for i in range(pg_addr,pg_addr+self.pagesize, (self.wordsize//8))])
			if cmd[2] == 0x61B061B0:
				print("Writeback page " + hex(addr))
				ret = yield from riffa.channel_read(selfp.simulator, self.data_rx)
				print("Modified:")
				for i in range(len(ret)):
					if ret[i] != generate_data(addr+i*(self.wordsize//8)):
						self.modified[addr+i*(self.wordsize//8)] = ret[i]
						print(hex(addr+i*(self.wordsize//8)) + ": " + str(ret[i]))

	gen_simulation.passive = True


class TB(Module):
	def __init__(self):
		c_pci_data_width = 128
		num_chnls = 2
		combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
		combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

		self.submodules.dut = virtmem.VirtmemWrapper(combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, drive_clocks=False)

		self.submodules.channelsplitter = riffa.ChannelSplitter(combined_interface_tx, combined_interface_rx)
		tx0, rx0 = self.channelsplitter.get_channel(0)
		tx1, rx1 = self.channelsplitter.get_channel(1)

		self.submodules.tbmem = TBMemory(tx0, rx0, tx1, rx1, c_pci_data_width=c_pci_data_width)

	def gen_simulation(self, selfp):
		transactions = [
		(0x604000, 0), 
		(0x604004, 0), 
		(0x604008, 1),
		(0x597a004, 0), 
		(0xfffe000, 0), 
		(0x8, 1), 
		(0x45600c, 0), 
		(0x604000, 0), 
		(0x604008, 1)
		]
		for addr, we in transactions:
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
		selfp.dut.virtmem.flush_all = 1
		yield 2
		while not selfp.dut.virtmem.done:
			yield
		# for i in range(1024):
		# 	a, b, c, d = riffa.unpack(selfp.simulator.rd(self.dut.virtmem.mem, i), 4)
		# 	print("{0:04x}: {1:08x} {2:08x} {3:08x} {4:08x}".format(i*16, a, b, c, d))
		# yield



if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd", ncycles=10000)
