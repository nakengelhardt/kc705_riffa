import sys

from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState

from migen.fhdl import verilog

import riffa

class GenericRiffa(Module):
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, num_chnls=1, drive_clocks=True):
		self.combined_interface_tx = combined_interface_tx
		self.combined_interface_rx = combined_interface_rx
		self._max_channels = num_chnls
		self._num_channels = 0
		self.c_pci_data_width = c_pci_data_width
		if drive_clocks:
			self.rx_clk = Signal(self._max_channels)
			self.tx_clk = Signal(self._max_channels)
			self.comb += [ self.rx_clk[i].eq(ClockSignal()) for i in range(self._max_channels) ]
			self.comb += [ self.tx_clk[i].eq(ClockSignal()) for i in range(self._max_channels) ]


	def get_channel(self):	
		if self._num_channels < self._max_channels:
			channel_rx = riffa.Interface(data_width=self.c_pci_data_width)
			channel_tx = riffa.Interface(data_width=self.c_pci_data_width)
			for name in "start", "last", "data_valid":
				self.comb += getattr(self.combined_interface_tx, name)[self._num_channels].eq(getattr(channel_tx, name))
				self.comb += getattr(channel_rx, name).eq(getattr(self.combined_interface_rx, name)[self._num_channels])
			for name in "ack", "data_ren":
				self.comb += getattr(channel_tx, name).eq(getattr(self.combined_interface_tx, name)[self._num_channels])
				self.comb += getattr(self.combined_interface_rx, name)[self._num_channels].eq(getattr(channel_rx, name))
			self.comb += self.combined_interface_tx.data[self._num_channels*self.c_pci_data_width:(self._num_channels+1)*self.c_pci_data_width].eq(channel_tx.data)
			self.comb += channel_rx.data.eq(self.combined_interface_rx.data[self._num_channels*self.c_pci_data_width:(self._num_channels+1)*self.c_pci_data_width])
			self.comb += self.combined_interface_tx.len[self._num_channels*32:(self._num_channels+1)*32].eq(channel_tx.len)
			self.comb += channel_rx.len.eq(self.combined_interface_rx.len[self._num_channels*32:(self._num_channels+1)*32])
			self.comb += self.combined_interface_tx.off[self._num_channels*31:(self._num_channels+1)*31].eq(channel_tx.off)
			self.comb += channel_rx.off.eq(self.combined_interface_rx.off[self._num_channels*31:(self._num_channels+1)*31])
			self._num_channels += 1
			return channel_rx, channel_tx
		else:
			raise ValueError("No more channels fit in combined interface")



class Virtmem(GenericRiffa):
	def __init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=32, num_chnls=1, drive_clocks=True):
		GenericRiffa.__init__(self, combined_interface_rx, combined_interface_tx, c_pci_data_width=c_pci_data_width, num_chnls=num_chnls, drive_clocks=True)

		if drive_clocks:
			self.clock_domains.cd_sys = ClockDomain()

		rx0, tx0 = self.get_channel()
		rx1, tx1 = self.get_channel()
		self.comb += rx0.connect(tx1) , rx1.connect(tx0)


def main():
	c_pci_data_width = 128
	num_chnls = 2
	combined_interface_tx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)
	combined_interface_rx = riffa.Interface(data_width=c_pci_data_width, num_chnls=num_chnls)

	m = Virtmem(combined_interface_rx, combined_interface_tx, c_pci_data_width=c_pci_data_width, num_chnls=num_chnls)
	m.cd_sys.clk.name_override="clk"
	m.cd_sys.rst.name_override="rst"
	for name in "ack", "last", "len", "off", "data", "data_valid", "data_ren":
		getattr(combined_interface_rx, name).name_override="chnl_rx_{}".format(name)
		getattr(combined_interface_tx, name).name_override="chnl_tx_{}".format(name)
	combined_interface_rx.start.name_override="chnl_rx"
	combined_interface_tx.start.name_override="chnl_tx"
	m.rx_clk.name_override="chnl_rx_clk"
	m.tx_clk.name_override="chnl_tx_clk"
	print(verilog.convert(m, name="Virtmem", ios={getattr(combined_interface_rx, name) for name in ["start", "ack", "last", "len", "off", "data", "data_valid", "data_ren"]} | {getattr(combined_interface_tx, name) for name in ["start", "ack", "last", "len", "off", "data", "data_valid", "data_ren"]} | {m.rx_clk, m.tx_clk, m.cd_sys.clk, m.cd_sys.rst} ))

if __name__ == '__main__':
	main()