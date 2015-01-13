from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import mm
import riffa
from virtmem_tb import TBMemory

# memory initialization function
def generate_data(addr):
	return (addr & 0x3FFF)>>1

class TB(Module):
	def __init__(self):
		c_pci_data_width = 128
		num_chnls = 3
		self.wordsize = 16
		ptrsize = 64
		combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
		combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

		# instantiate test "memory" module that responds to page fetch/writeback requests
		self.submodules.channelsplitter = riffa.ChannelSplitter(combined_interface_tx, combined_interface_rx)
		tx0, rx0 = self.channelsplitter.get_channel(0)
		tx1, rx1 = self.channelsplitter.get_channel(1)
		self.submodules.tbmem = TBMemory(tx0, rx0, tx1, rx1, c_pci_data_width=c_pci_data_width, wordsize=self.wordsize, ptrsize=ptrsize, init_fn=generate_data)

		# instantiate design under test
		self.submodules.dut = mm.MatMul(combined_interface_rx, combined_interface_tx, c_pci_data_width=c_pci_data_width, wordsize=self.wordsize, ptrsize=ptrsize, drive_clocks=False)
	
		# channel to send args / receive results
		# remember rx/tx from FPGA side -> write to rx, read from tx
		self.tx, self.rx = self.channelsplitter.get_channel(2)

	

	def gen_simulation(self, selfp):
		baseA = 0x6040000
		baseB = 0x6050000
		baseC = 0x6060000
		dim_i = 8
		dim_j = 8
		dim_k = 8
		arg_struct = []
		arg_struct.extend(riffa.unpack(baseA, 2))
		arg_struct.extend(riffa.unpack(baseB, 2))
		arg_struct.extend(riffa.unpack(baseC, 2))
		arg_struct.extend(riffa.unpack(dim_i, 2))
		arg_struct.extend(riffa.unpack(dim_j, 2))
		arg_struct.extend(riffa.unpack(dim_k, 2))
		assert(len(arg_struct) == 12)

		expectedA = [[generate_data(baseA + ((i * dim_k + k) << log2_int(self.wordsize//8))) for k in range(dim_k)] for i in range(dim_i)]
		expectedB = [[generate_data(baseB + ((k * dim_j + j) << log2_int(self.wordsize//8))) for j in range(dim_j)] for k in range(dim_k)]
		# calc expected result
		# C[i][j] += A[i][k]*B[k][j]
		expectedC = [[0 for j in range(dim_j)] for i in range(dim_i)]
		for i in range(dim_i):
			for j in range(dim_j):
				for k in range(dim_k):
					expectedC[i][j] +=  expectedA[i][k] * expectedB[k][j]


		print("A:")
		for row in expectedA:
			print(row)
		print("B:")
		for row in expectedB:
			print(row)
		print("C:")
		for row in expectedC:
			print(row)

		def run_matmul():
			# send arguments to DUT
			yield from riffa.channel_write(selfp.simulator, self.rx, arg_struct)

			# wait for return value
			ret = yield from riffa.channel_read(selfp.simulator, self.tx)

			yield from self.tbmem.send_flush_command(selfp)

			print("MatMul run " + str(run) + " finished. Reports " + str(riffa.pack(ret)) + " cycles taken.")

			# verify result matrix
			num_errors = 0
			for i in range(dim_i):
				for j in range(dim_j):
					# address "i"th word in range
					addr = baseC + ((i * dim_j + j) << log2_int(self.wordsize//8))
					# compare to expected
					if self.tbmem.read_mem(addr) != expectedC[i][j]:
						num_errors += 1
						# print a few errors but not too many
						if num_errors <= 10:
							print(hex(addr) + ": " + str(self.tbmem.read_mem(addr)) + " (expected " + str(expectedC[i][j]) + ")")
			if num_errors > 10:
				print("And " + str(num_errors-10) + " more.")

			yield

		num_runs = 3

		for run in range(num_runs):
			yield from run_matmul()

		self.tbmem.send_invalidate_command(selfp)

		yield from run_matmul()


if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd", keep_files=True, ncycles=200000)