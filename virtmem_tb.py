from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import virtmem
import riffa

def generate_data(addr):
	return (addr >> 32) & 0xFFFF | (addr & 0xFFFF)

class Writer(Module):
	def __init__(self, channel, data_to_send):
		self.channel = channel
		self.data_to_send = data_to_send

	def gen_simulation(self, selfp):
		addrs = []
		for i in self.data_to_send:
			addrs.extend(riffa.unpack(i, 2))
		yield from riffa.channel_write(selfp.simulator, self.channel, addrs)

class Reader(Module):
	def __init__(self, channel, data_to_recv):
		self.channel = channel
		self.data_to_recv = data_to_recv

	def gen_simulation(self, selfp):
		for data0, data1 in zip(self.data_to_recv[::2], self.data_to_recv[1::2]):
			words = yield from riffa.channel_read(selfp.simulator, self.channel)
			print(words)
			if data0 != words[0] or data1 != words[1]:
				print("Expected: {}".format((hex(data0),hex(data1))))
		yield


class TBMemory(Module):
	def __init__(self, cmd_rx, data_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, npagesincache=4, pagesize=4096):
		self.cmd_rx = cmd_rx
		self.data_tx = data_tx
		self.c_pci_data_width = c_pci_data_width
		self.wordsize = wordsize
		self.ptrsize = ptrsize
		self.npagesincache = npagesincache
		self.pagesize = pagesize

	def gen_simulation(self, selfp):
		while True:
			cmd = yield from riffa.channel_read(selfp.simulator, self.cmd_rx)
			if cmd[2] == 0x6e706e70:
				addr = (cmd[1] << 32) | cmd[0]
				print("Fetching page " + hex(addr))
				pg_addr = (addr >> log2_int(self.pagesize)) << log2_int(self.pagesize) 
				yield from riffa.channel_write(selfp.simulator, self.data_tx, [generate_data(i) for i in range(pg_addr,pg_addr+self.pagesize, 4)])
	gen_simulation.passive = True


class TB(Module):
	def __init__(self):
		c_pci_data_width = 128
		num_chnls = 3
		combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
		combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

		self.submodules.dut = virtmem.UserCode(combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, drive_clocks=False)

		self.submodules.channelsplitter = riffa.ChannelSplitter(combined_interface_tx, combined_interface_rx)
		tx0, rx0 = self.channelsplitter.get_channel(0)
		tx1, rx1 = self.channelsplitter.get_channel(1)
		tx2, rx2 = self.channelsplitter.get_channel(2)

		data_to_send = [0x604000, 0x604004, 0x597a004, 0xfffe000, 0x8, 0x45600c, 0x604000, 0x604008]
		self.submodules.writer = Writer(rx2, data_to_send)
		self.submodules.reader = Reader(tx2, [generate_data(x) for x in data_to_send])

		self.submodules.tbmem = TBMemory(tx0, rx1, c_pci_data_width=c_pci_data_width)

	# def do_simulation(self, selfp):
	# 	if selfp.dut.virtmem.replacement_policy.hit:
	# 		for i in range(1024):
	# 			a, b, c, d = riffa.unpack(selfp.simulator.rd(self.dut.virtmem.mem, i), 4)
	# 			print("{0:04x}: {1:08x} {2:08x} {3:08x} {4:08x}".format(i*16, a, b, c, d))
		
	# gen_simulation.passive = True

if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd", ncycles=5000)
