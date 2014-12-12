from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState, NextValue

from migen.fhdl import verilog

import riffa, replacementpolicies
from virtmem import VirtmemWrapper

class MatMul(VirtmemWrapper):
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, wordsize=32, ptrsize=64, drive_clocks=True):
		VirtmemWrapper.__init__(self, combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, wordsize=wordsize, ptrsize=ptrsize, drive_clocks=drive_clocks)

		###
		rx, tx = self.get_channel(2)

		## MM variables
		baseA = Signal(ptrsize)
		baseB = Signal(ptrsize)
		baseC = Signal(ptrsize)

		# these hold the values (i+1), (j+1), (k+1) 
		# because check for boundary is done before incrementation 
		# and no time to put additions in nested If conditions
		i = Signal(16)
		j = Signal(16)
		k = Signal(16)

		dim_i = Signal(16)
		dim_j = Signal(16)
		dim_k = Signal(16)

		rowA = Signal(ptrsize)
		colB = Signal(ptrsize)

		currA = Signal(ptrsize)
		currB = Signal(ptrsize)
		currC = Signal(ptrsize)

		incrA = Signal(ptrsize)
		incrB = Signal(ptrsize)
		incrC = Signal(ptrsize)

		Cij = Signal(wordsize)
		Aik0 = Signal(wordsize)
		Bkj0 = Signal(wordsize)
		Aik1 = Signal(wordsize)
		Bkj1 = Signal(wordsize)
		ires0 = Signal(wordsize)
		ires1 = Signal(wordsize)

		calc_enable = Signal()
		last_in = Signal()
		pipeline_stages = 4
		validity = Signal(pipeline_stages)
		res_valid = Signal()
		clear_Cij = Signal()

		self.comb += res_valid.eq(validity[-1])

		calc_enable_n = Signal()
		last_in_n = Signal()
		self.sync += calc_enable.eq(calc_enable_n), last_in.eq(last_in_n)

		### for i,j,k: C[i][j] += A[i][k]*B[k][j]
		self.sync += If(calc_enable, validity.eq(validity << 1 | last_in), Aik1.eq(Aik0), Bkj1.eq(Bkj0), ires0.eq(Aik1*Bkj1), ires1.eq(ires0), Cij.eq(Cij + ires1))
		self.sync += If(clear_Cij, Cij.eq(0))

		## rx/tx variables
		arg_struct_size = 3 * 64 * 2 # (baseA, baseB, baseC, dim_i, dim_j, dim_k) each 64b
		arg_struct = Signal(arg_struct_size)

		res_struct_size = 64
		res_struct = Signal(res_struct_size)

		cycles_taken = Signal(res_struct_size)
		reset_cycles = Signal()
		self.sync += If(reset_cycles, cycles_taken.eq(0)).Else(cycles_taken.eq(cycles_taken + 1))
		self.comb += res_struct.eq(cycles_taken)

		fsm = FSM()
		self.submodules += fsm

		fsm.act("IDLE", #0
			reset_cycles.eq(1),
			If(rx.start,
				If(rx.len == arg_struct_size//32, # avoids getting stuck in recv when incomplete transmission of args
					NextState("RECEIVE0")
				).Else( # just delete incomplete args
					rx.ack.eq(1),
					rx.data_ren.eq(1)
				)
			)
		)
		for n in range(arg_struct_size//c_pci_data_width):
			begin = [] if n==0 else arg_struct[:n*c_pci_data_width]
			end = [] if n==arg_struct_size//c_pci_data_width-1 else arg_struct[(n+1)*c_pci_data_width:]
			fsm.act("RECEIVE" + str(n), # 1,2,3
				rx.ack.eq(1),
				If(rx.data_valid,
					rx.data_ren.eq(1),
					NextValue(arg_struct, Cat(begin, rx.data, end)),
					NextState("RECEIVE" + str(n+1))
				)
			)
		fsm.act("RECEIVE" + str(arg_struct_size//c_pci_data_width), #4
			NextValue(baseA, arg_struct[0:64]),
			NextValue(baseB, arg_struct[64:2*64]),
			NextValue(baseC, arg_struct[2*64:3*64]),
			NextValue(dim_i, arg_struct[3*64:4*64]),
			NextValue(dim_j, arg_struct[4*64:5*64]),
			NextValue(dim_k, arg_struct[5*64:6*64]),

			NextValue(currA, arg_struct[0:64]), # baseA
			NextValue(currB, arg_struct[64:2*64]), # baseB
			NextValue(currC, arg_struct[2*64:3*64]), # baseC

			NextValue(rowA, arg_struct[0:64]), # baseA
			NextValue(colB, arg_struct[64:2*64]), # baseB

			NextValue(incrA, 1 << log2_int(wordsize//8)), # 1 word
			NextValue(incrB, arg_struct[4*64:5*64 - log2_int(wordsize//8)] << log2_int(wordsize//8)), # dim_j words
			NextValue(incrC, 1 << log2_int(wordsize//8)), # 1 word
			
			NextValue(i, 1),
			NextValue(j, 1),
			NextValue(k, 1),
			NextState("GET_A")
		)
		### for i,j,k: C[i][j] += A[i][k]*B[k][j]

		fsm.act("GET_A", #5
			self.virtmem.virt_addr.eq(currA),
			self.virtmem.req.eq(1),
			self.virtmem.write_enable.eq(0),
			If(self.virtmem.done,
				self.virtmem.req.eq(0),
				NextValue(Aik0, self.virtmem.data_read),
				NextValue(currA, currA + incrA),
				NextState("GET_B")
			)
		)
		fsm.act("GET_B", #6
			self.virtmem.virt_addr.eq(currB),
			self.virtmem.req.eq(1),
			self.virtmem.write_enable.eq(0),
			If(self.virtmem.done,
				self.virtmem.req.eq(0),
				NextValue(Bkj0, self.virtmem.data_read),
				NextValue(currB, currB + incrB),
				NextValue(k, k + 1),
				calc_enable_n.eq(1),
				If(k < dim_k,
					NextState("GET_A")
				).Else(
					last_in_n.eq(1),
					NextState("WAIT_RES")
				)
			)
		)
		fsm.act("WAIT_RES", #7
			NextValue(Aik0, 0),
			NextValue(Bkj0, 0),
			If(res_valid,
				NextState("PUT_C")
			).Else(
				calc_enable_n.eq(1)
			)
		)
		fsm.act("PUT_C", #8
			self.virtmem.virt_addr.eq(currC),
			self.virtmem.write_enable.eq(1),
			self.virtmem.data_write.eq(Cij),
			self.virtmem.req.eq(1),
			If(self.virtmem.done,
				self.virtmem.req.eq(0),
				clear_Cij.eq(1),
				NextValue(currC, currC + incrC),
				NextState("ADVANCE_LOOP")
			)
		)
		fsm.act("ADVANCE_LOOP", #9
			If(j < dim_j,
				NextValue(j, j + 1),
				NextValue(k, 1),
				NextValue(currB, baseB + (j << log2_int(wordsize//8))),
				NextValue(currA, rowA),
				NextState("GET_A")
			).Else(
				If(i < dim_i,
					NextValue(i, i + 1),
					NextValue(j, 1),
					NextValue(k, 1),
					NextValue(currB, baseB),
					NextValue(rowA, rowA + (dim_k << log2_int(wordsize//8))),
					NextValue(currA, rowA + (dim_k << log2_int(wordsize//8))),
					NextState("GET_A")
				).Else( # calculation done, if still valid results in pipeline, finish writing
					If(validity != 0,
						calc_enable_n.eq(1),
						NextState("PUT_C")
					).Else(
						NextState("FLUSH")
					)
				)
			)
		)

		# flush virtmem cache modifications to main memory
		fsm.act("FLUSH", #10
			self.virtmem.flush_all.eq(1),
			If(self.virtmem.done,
				NextState("TRANSMIT_INIT")
			)
		)
		# send function return struct
		fsm.act("TRANSMIT_INIT", #11
			tx.start.eq(1),
			tx.len.eq(res_struct_size//32),
			tx.last.eq(1),
			If(tx.ack,
				NextState("TRANSMIT0")
			)
		)
		for n in range(max(1, res_struct_size//c_pci_data_width)):
			fsm.act("TRANSMIT" + str(n), #12
				tx.start.eq(1),
				tx.len.eq(res_struct_size//32),
				tx.last.eq(1),
				tx.data_valid.eq(1),
				tx.data.eq(res_struct[n*c_pci_data_width:min((n+1)*c_pci_data_width, res_struct_size)]),
				If(tx.data_ren,
					NextState("TRANSMIT" + str(n+1))
				)
			)
		fsm.act("TRANSMIT" + str(max(1, res_struct_size//c_pci_data_width)), #transmission finished
			NextState("IDLE")
		)

def main():
	c_pci_data_width = 128
	num_chnls = 3
	wordsize = 16
	ptrsize = 64
	combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
	combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

	m = MatMul(combined_interface_rx=combined_interface_rx, combined_interface_tx=combined_interface_tx, c_pci_data_width=c_pci_data_width, wordsize=wordsize, ptrsize=ptrsize)
	m.cd_sys.clk.name_override="clk"
	m.cd_sys.rst.name_override="rst"
	for name in "ack", "last", "len", "off", "data", "data_valid", "data_ren":
		getattr(combined_interface_rx, name).name_override="chnl_rx_{}".format(name)
		getattr(combined_interface_tx, name).name_override="chnl_tx_{}".format(name)
	combined_interface_rx.start.name_override="chnl_rx"
	combined_interface_tx.start.name_override="chnl_tx"
	m.rx_clk.name_override="chnl_rx_clk"
	m.tx_clk.name_override="chnl_tx_clk"
	print(verilog.convert(m, name="top", ios={getattr(combined_interface_rx, name) for name in ["start", "ack", "last", "len", "off", "data", "data_valid", "data_ren"]} | {getattr(combined_interface_tx, name) for name in ["start", "ack", "last", "len", "off", "data", "data_valid", "data_ren"]} | {m.rx_clk, m.tx_clk, m.cd_sys.clk, m.cd_sys.rst} ))


if __name__ == '__main__':
	main()
