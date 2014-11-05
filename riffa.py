from migen.fhdl.std import *
from migen.genlib import roundrobin
from migen.genlib.record import *
from migen.genlib.misc import optree, chooser
from migen.genlib.fsm import FSM, NextState
from migen.bus.transactions import *

_layout = [
	("start",		"num_chnls",				DIR_M_TO_S),
	("ack",			"num_chnls",				DIR_S_TO_M),
	("last",		"num_chnls",				DIR_M_TO_S),
	("len",			"num_chnls_x_32",			DIR_M_TO_S),
	("off",			"num_chnls_x_31",			DIR_M_TO_S),
	("data",		"data_width_x_num_chnls",	DIR_M_TO_S),
	("data_valid",	"num_chnls",				DIR_M_TO_S),
	("data_ren",	"num_chnls",				DIR_S_TO_M)
]

class Interface(Record):
	def __init__(self, num_chnls=1, data_width=32, channel_number=None):
		Record.__init__(self, set_layout_parameters(_layout,
			num_chnls=num_chnls, num_chnls_x_32=32*num_chnls, num_chnls_x_31=31*num_chnls, data_width_x_num_chnls=data_width*num_chnls))
		self.num_chnls = num_chnls
		self.data_width = data_width
		self.channel_number = channel_number


class ChannelSplitter(Module):
	def __init__(self, combined_master, combined_slave):
		self.combined_master = combined_master
		self.combined_slave = combined_slave
		assert(combined_slave.num_chnls == combined_master.num_chnls)
		self.data_width = combined_master.data_width

		self.subchannels = {}
		for i in range(combined_master.num_chnls):
			channel_m = Interface(data_width=self.data_width, channel_number=i)
			channel_s = Interface(data_width=self.data_width, channel_number=i)
			for name in "start", "last", "data_valid":
				self.comb += getattr(self.combined_slave, name)[i].eq(getattr(channel_s, name))
				self.comb += getattr(channel_m, name).eq(getattr(self.combined_master, name)[i])
			for name in "ack", "data_ren":
				self.comb += getattr(channel_s, name).eq(getattr(self.combined_slave, name)[i])
				self.comb += getattr(self.combined_master, name)[i].eq(getattr(channel_m, name))
			self.comb += self.combined_slave.data[i*self.data_width:(i+1)*self.data_width].eq(channel_s.data)
			self.comb += channel_m.data.eq(self.combined_master.data[i*self.data_width:(i+1)*self.data_width])
			self.comb += self.combined_slave.len[i*32:(i+1)*32].eq(channel_s.len)
			self.comb += channel_m.len.eq(self.combined_master.len[i*32:(i+1)*32])
			self.comb += self.combined_slave.off[i*31:(i+1)*31].eq(channel_s.off)
			self.comb += channel_m.off.eq(self.combined_master.off[i*31:(i+1)*31])
			self.subchannels[i] = (channel_m, channel_s)

	def get_channel(self, i):
		return self.subchannels[i]


def pack(words):
	data = 0
	for i, word in enumerate(words):
		data = data | ((word & 0xFFFFFFFF) << i*32)
	return data

def unpack(data, n):
	words = []
	for i in range(n):
		words.append((data >> i*32) & 0xFFFFFFFF)
	return words

def channel_write(sim, channel, words):
	wordsize = 32
	channelwidth = channel.data_width//wordsize
	nwords = len(words)
	sim.wr(channel.start, 1)
	sim.wr(channel.last, 1)
	sim.wr(channel.len, nwords)
	sim.wr(channel.off, 0)
	nsent = 0
	while not sim.rd(channel.ack):
		yield
	while nsent < nwords:
		data = pack(words[nsent:min(nsent+channelwidth, nwords)])
		sim.wr(channel.data, data)
		sim.wr(channel.data_valid, 1)
		yield
		while not sim.rd(channel.data_ren):
			yield
		print(("Channel "+str(channel.channel_number)+": " if channel.channel_number != None else "") + "Sent data " + str(words[nsent:min(nsent+channelwidth, nwords)]) + " ({0:032x})".format(data))
		nsent += channelwidth
	sim.wr(channel.start, 0)
	sim.wr(channel.last, 0)
	sim.wr(channel.len, 0)
	sim.wr(channel.data, 0)
	sim.wr(channel.data_valid, 0)

def channel_read(sim, channel):
	wordsize = 32
	channelwidth = channel.data_width//wordsize
	words = []
	# print("Waiting for transaction start on channel {0}...".format(str(channel)))
	while not sim.rd(channel.start):
		yield
	# print("Transaction started")
	nwords = sim.rd(channel.len)
	nrecvd = 0
	sim.wr(channel.ack, 1)
	yield
	sim.wr(channel.ack, 0)
	yield
	while nrecvd < nwords:
		# print("Waiting for data word #" + str(nrecvd))
		while not sim.rd(channel.data_valid):
			yield
		data = sim.rd(channel.data)
		print(("Channel "+str(channel.channel_number)+": " if channel.channel_number != None else "") + "Received data " + str(unpack(data, min(channelwidth, nwords-nrecvd))) + " ({0:032x})".format(data))
		words.extend(unpack(data, min(channelwidth, nwords-nrecvd)))
		nrecvd += channelwidth
		sim.wr(channel.data_ren, 1)
		yield
		sim.wr(channel.data_ren, 0)
		yield
	return words