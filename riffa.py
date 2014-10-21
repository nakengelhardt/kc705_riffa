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