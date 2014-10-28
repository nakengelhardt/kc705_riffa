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
	def __init__(self, num_chnls=1, data_width=32):
		Record.__init__(self, set_layout_parameters(_layout,
			num_chnls=num_chnls, num_chnls_x_32=32*num_chnls, num_chnls_x_31=31*num_chnls, data_width_x_num_chnls=data_width*num_chnls))
		self.num_chnls = num_chnls
		self.data_width = data_width

class ChannelSplitter(Module):
	def __init__(self, combined_master, combined_slave):
		self.combined_master = combined_master
		self.combined_slave = combined_slave
		assert(combined_slave.num_chnls == combined_master.num_chnls)
		self.data_width = combined_master.data_width

		self.subchannels = {}
		for i in range(combined_master.num_chnls):
			channel_m = Interface(data_width=self.data_width)
			channel_s = Interface(data_width=self.data_width)
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


def channel_write(channelp, words):
	channelp.start = 1
	channelp.last = 1
	channelp.len = len(words)
	channelp.off = 0
	while not channelp.ack:
		yield
	for word in words:
		print("Sending data " + str(word))
		channelp.data = word
		channelp.data_valid = 1
		yield
		while not channelp.data_ren:
			yield
	channelp.start = 0
	channelp.last = 0
	channelp.len = 0
	channelp.data = 0
	channelp.data_valid = 0

def channel_read(channelp):
	words = []
	while not channelp.start:
		yield
	nwords = channelp.len
	channelp.ack = 1
	yield
	channelp.ack = 0
	yield
	for i in range(nwords):
		while not channelp.data_valid:
			yield
		words.append(channelp.data)
		channelp.data_ren = 1
		yield
		channelp.data_ren = 0
		yield
	return words