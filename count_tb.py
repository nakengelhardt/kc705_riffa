from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import count
import riffa
from virtmem_tb import TBMemory

# memory initialization function
def generate_data(addr):
	return (addr & 0x3FFF)>>2

class TB(Module):
	def __init__(self):
		c_pci_data_width = 128
		num_chnls = 3
		self.wordsize = 32
		self.ptrsize = 64
		combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
		combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

		# instantiate test "memory" module that responds to page fetch/writeback requests
		self.submodules.channelsplitter = riffa.ChannelSplitter(combined_interface_tx, combined_interface_rx)
		tx0, rx0 = self.channelsplitter.get_channel(0)
		tx1, rx1 = self.channelsplitter.get_channel(1)
		self.submodules.tbmem = TBMemory(tx0, rx0, tx1, rx1, c_pci_data_width=c_pci_data_width, init_fn=generate_data)

		# instantiate design under test
		self.submodules.dut = count.Count(combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, wordsize=self.wordsize, ptrsize=self.ptrsize, drive_clocks=False)
	
		# channel to send args / receive results
		# remember rx/tx from FPGA side -> write to rx, read from tx
		self.tx, self.rx = self.channelsplitter.get_channel(2)


	def gen_simulation(self, selfp):
		# memory area to work on
		baseaddr = 0x222000 ## TODO
		size = 4096 ## TODO
		# function argument to send (as list of 32 bit words)
		arg_struct = []
		arg_struct.extend(riffa.unpack(baseaddr, 2))
		arg_struct.extend(riffa.unpack(size, 2))
		# expected return value (as list of 32 bit words)
		expected_ret = [size] ## TODO 
		# expected memory modifications (in memory words of size 'wordsize')
		expected_results = [generate_data(baseaddr + i << log2_int(self.wordsize//8)) for i in range(size)] ## TODO

		# send arguments to DUT
		yield from riffa.channel_write(selfp.simulator, self.rx, arg_struct)

		# wait for return value
		ret = yield from riffa.channel_read(selfp.simulator, self.tx)

		# check return value
		if ret != expected_ret:
			## TODO
			print("Wrong return value! Expected " + str(expected_ret) + ", received " + str(ret))

		# check memory modifications
		num_errors = 0
		for i in range(size):
			# address "i"th word in range
			addr = baseaddr + i << log2_int(self.wordsize//8)
			# compare to expected
			if self.tbmem.read_mem(addr) != expected_results[i]:
				num_errors += 1
				# print a few errors but not too many
				if num_errors <= 10:
					print(hex(addr) + ": " + str(self.tbmem.read_mem(addr)) + " (expected " + str(expected_results[i]) + ")")
		if num_errors > 10:
			print("And " + str(num_errors-10) + " more.")
		if num_errors == 0:
			print("Test passed.")

if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd", keep_files=True, ncycles=100000)