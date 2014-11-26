import sys, operator, functools

from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import whoosh
import riffa
from virtmem_tb import TBMemory

def generate_data(addr):
	return (addr & 0x3FFF)>>2

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
		self.done = 0

	def gen_simulation(self, selfp):
		errors = 0
		for data in self.data_to_recv:
			words = yield from riffa.channel_read(selfp.simulator, self.channel)
			print(words)
			if data != words[0]:
				errors += 1
				print("Expected: {}".format(hex(data)))
		yield
		print(str(errors) + " error(s) in received data.")
		self.done = 1


class TB(Module):
	def __init__(self):
		c_pci_data_width = 128
		num_chnls = 3
		combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
		combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

		self.submodules.dut = whoosh.Whoosh(combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, drive_clocks=False)

		self.submodules.channelsplitter = riffa.ChannelSplitter(combined_interface_tx, combined_interface_rx)
		tx0, rx0 = self.channelsplitter.get_channel(0)
		tx1, rx1 = self.channelsplitter.get_channel(1)
		tx2, rx2 = self.channelsplitter.get_channel(2)

		xy_range = 4096
		self.data_to_send = [0x604000, xy_range]
		self.results = [functools.reduce(operator.xor, (generate_data((x+i)<<2) for i in range(3)), 0) for x in range(xy_range - 2)] + [generate_data((xy_range - 2)<<2)] + [generate_data((xy_range - 1)<<2)]
		self.submodules.writer = Writer(rx2, self.data_to_send)
		self.submodules.reader = Reader(tx2, [xy_range])

		self.submodules.tbmem = TBMemory(tx0, rx0, tx1, rx1, c_pci_data_width=c_pci_data_width, init_fn=generate_data)

	def gen_simulation(self, selfp):
		while not self.reader.done:
			yield
		yield from riffa.channel_write(selfp.simulator, self.tbmem.cmd_tx, [0xF1005])
		while not self.tbmem.flushack:
			yield
		addr = self.data_to_send[0]
		num_errors = 0
		for i in range(self.data_to_send[1]):
			if self.tbmem.read_mem(addr) != self.results[i]:
				num_errors += 1
				if num_errors <= 10:
					print(hex(addr) + ": " + str(self.tbmem.read_mem(addr)) + " (should be " + str(self.results[i]) + ")")
			addr += 4
		if num_errors > 10:
			print("And " + str(num_errors-10) + " more.")
		i = self.data_to_send[1] - 2
		addr = self.data_to_send[0] + (i << 2)
		print(hex(addr) + ": " + str(self.tbmem.read_mem(addr)))
		print(self.results[i])
		i = self.data_to_send[1] - 1
		addr = self.data_to_send[0] + (i << 2)
		print(hex(addr) + ": " + str(self.tbmem.read_mem(addr)))
		print(self.results[i])
		yield 10
	# gen_simulation.passive = True

if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd", ncycles=100000)
