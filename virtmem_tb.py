import random
random.seed(6)

from migen.fhdl.std import *
from migen.sim.generic import run_simulation

import virtmem
import riffa

def generate_data_fn(wordsize=32):
	def generate_data(addr):
		if wordsize < 16:
			mask = 0xFF
		else:
			mask = 0xFFFF
		return (addr & mask)
	return generate_data


class TBMemory(Module):
	def __init__(self, cmd_rx, cmd_tx, data_rx, data_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, npagesincache=4, pagesize=4096, init_fn=generate_data_fn()):
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
				# print("Receiving command...")
				cmd = yield from riffa.channel_read(selfp.simulator, self.cmd_rx)
				addr = (cmd[1] << 32) | cmd[0] if self.ptrsize > 32 else cmd[0]
				pg_addr = (addr >> log2_int(self.pagesize)) << log2_int(self.pagesize) 
				assert(addr == pg_addr)
				if cmd[2] == 0x6e706e70:
					print("Fetching page " + hex(addr))
					data = []
					if self.wordsize < 32:
						mask = 1
						for i in range(self.wordsize):
							mask = mask | (1 << i)
						for i in range(pg_addr, pg_addr+self.pagesize, 4):
							d = 0
							for j in range(0,32//self.wordsize):
								d = d | ((self.read_mem(i+ j*(self.wordsize//8)) & mask) << j*self.wordsize)
							data.append(d)
					else:
						for i in range(pg_addr, pg_addr+self.pagesize, (self.wordsize//8)):
							data.extend(riffa.unpack(self.read_mem(i), self.wordsize//32))
					if len(data) != self.pagesize//4:
						print("Wrong page length: " + str(len(data)))
					yield from riffa.channel_write(selfp.simulator, self.data_tx, data)
					# print("Finished fetching page.")
				if cmd[2] == 0x61B061B0:
					print("Writeback page " + hex(addr))
					# print(ret)
					if len(ret) < self.pagesize//4:
						print("Incomplete writeback: received only " + str(len(ret)) + " words")
					if self.wordsize >= 32:
						words = [riffa.pack(x) for x in zip(*[ret[i::self.wordsize//32] for i in range(self.wordsize//32)])]
					else:
						words = []
						mask = 1
						for i in range(self.wordsize):
							mask = mask | (1 << i)
						for i in range(len(ret)):
							for j in range(32//self.wordsize):
								words.append((ret[i] >> j*self.wordsize) & mask)
					print("Modified:")
					num_modified = 0
					for i in range(len(words)):
						if words[i] != self.read_mem(addr+i*(self.wordsize//8)):
							num_modified += 1
							self.modified[addr+i*(self.wordsize//8)] = words[i]
							if num_modified < 10:
								print(hex(addr+i*(self.wordsize//8)) + ": " + hex(words[i]))
					if num_modified >= 10:
						print("and more... " + str(num_modified) + " total.")
					ret = []
					# print("Finished writing back page.")
				if cmd[2] == 0xD1DF1005:
					self.flushack = 1
					print("Cache finished flushing.")
			elif selfp.data_rx.start:
				# print("Receiving data...")
				ret = yield from riffa.channel_read(selfp.simulator, self.data_rx)
				# print("Finished receiving data.")
			else:
				# print("Nothing")
				yield
					

	gen_simulation.passive = True

	def send_flush_command(self, selfp):
		self.flushack = 0
		yield from riffa.channel_write(selfp.simulator, self.cmd_tx, [0xF1005])
		while self.flushack == 0:
			yield
		self.flushack = 0

	def send_invalidate_command(self, selfp):
		yield from riffa.channel_write(selfp.simulator, self.cmd_tx, [0xC105E])


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

		self.submodules.tbmem = TBMemory(tx0, rx0, tx1, rx1, 
			c_pci_data_width=c_pci_data_width, 
			wordsize=self.wordsize, 
			ptrsize=self.ptrsize,
			init_fn=generate_data_fn(self.wordsize))


	def generate_random_address(self):
		pages = [0x604000, 0x597a000, 0x456000, 0xfffe000, 0x7868000, 0x222000, 0xaa45000]
		pg = random.choice(pages)
		off = random.randrange(0,self.pagesize*8//self.wordsize)
		return pg + (off<<log2_int(self.wordsize//8))

	def generate_random_transactions(self, num):
		for i in range(num):
			yield (self.generate_random_address(), random.randint(0,1))


	def gen_simulation(self, selfp):
		generate_data = generate_data_fn(self.wordsize)
		for addr, we in self.generate_random_transactions(24):
			selfp.dut.virtmem.virt_addr = addr
			selfp.dut.virtmem.num_words = 1
			selfp.dut.virtmem.req = 1
			selfp.dut.virtmem.write_enable = we
			if we:
				selfp.dut.virtmem.data_write = generate_data(addr) + 1
			yield
			selfp.dut.virtmem.req = 0
			while not selfp.dut.virtmem.done:
				yield
			if we:
				print("Wrote data " + hex(generate_data(addr) + 1) + " to address " + hex(addr))
			else:
				print("Read data " + hex(selfp.dut.virtmem.data_read) + " from address " + hex(addr))
		selfp.dut.virtmem.virt_addr = 0
		selfp.dut.virtmem.req = 0
		selfp.dut.virtmem.data_write = 0
		selfp.dut.virtmem.write_enable = 0
		yield
		num_words = 8
		addr = 0x456FF0
		selfp.dut.virtmem.virt_addr = addr
		selfp.dut.virtmem.num_words = num_words
		selfp.dut.virtmem.req = 1
		print("Requesting read burst of " + str(num_words) + " words starting from address " + hex(addr))
		internal_address = addr
		words_recvd = 0
		while words_recvd < num_words:
			yield
			if selfp.dut.virtmem.data_valid:
				words_recvd += 1
				print("Read " + hex(selfp.dut.virtmem.data_read) + " from address " + hex(internal_address))
				internal_address = selfp.dut.virtmem.virt_addr_internal

		selfp.dut.virtmem.virt_addr = 0
		selfp.dut.virtmem.req = 0
		selfp.dut.virtmem.data_write = 0
		selfp.dut.virtmem.write_enable = 0

		yield

		num_words = 8
		addr = 0x456FF0
		selfp.dut.virtmem.virt_addr = addr
		selfp.dut.virtmem.num_words = num_words
		selfp.dut.virtmem.req = 1
		selfp.dut.virtmem.write_enable = 1
		selfp.dut.virtmem.data_write = 0xBAE

		print("Requesting write burst of " + str(num_words) + " words starting from address " + hex(addr))
		internal_address = addr
		words_sent = 0
		while words_sent < num_words:
			selfp.dut.virtmem.data_write = words_sent
			yield
			if selfp.dut.virtmem.write_ack:
				words_sent += 1
				internal_address = selfp.dut.virtmem.virt_addr_internal
				print("Wrote " + hex(selfp.dut.virtmem.data_write) + " to address " + hex(internal_address))


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

		yield 20

		print("Simulation took " + str(selfp.simulator.cycle_counter) + " cycles.")
		# for i in range(1024):
		# 	a, b, c, d = riffa.unpack(selfp.simulator.rd(self.dut.virtmem.mem, i), 4)
		# 	print("{0:04x}: {1:08x} {2:08x} {3:08x} {4:08x}".format(i*16, a, b, c, d))
		# yield



if __name__ == "__main__":
	tb = TB()
	run_simulation(tb, vcd_name="tb.vcd", keep_files=True, ncycles=30000)
