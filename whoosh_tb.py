from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import whoosh
import riffa
from virtmem_tb import TBMemory

def generate_data(addr):
	return (addr & 0xFFFF)>>2

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

		data_to_send = [0x6040000, 5 << 32 | 5]
		self.results = [sum(generate_data((x+i)<<2) for i in range(3)) for x in range(5*5 - 2)] + [generate_data((5*5 - 2)<<2) + generate_data((5*5 - 1)<<2)*2] + [generate_data((5*5 - 1)<<2)*3]
		self.submodules.writer = Writer(rx2, data_to_send)
		self.submodules.reader = Reader(tx2, [5*5])

		self.submodules.tbmem = TBMemory(tx0, rx0, tx1, rx1, c_pci_data_width=c_pci_data_width, init_fn=generate_data)

	def gen_simulation(self, selfp):
		while not self.reader.done:
			yield
		yield from riffa.channel_write(selfp.simulator, self.tbmem.cmd_tx, [0xF1005])
		while not self.tbmem.flushack:
			yield
		addr = 0x6040000
		for i in range(25):
			if self.tbmem.read_mem(addr) != self.results[i]:
				print(hex(addr) + ": " + str(self.tbmem.read_mem(addr)) + " (should be " + str(self.results[i]) + ")")
			addr += 4
		
	# gen_simulation.passive = True

if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd", ncycles=5000)
