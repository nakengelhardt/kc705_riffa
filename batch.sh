#!/bin/bash

XIL_SETTINGS=/opt/Xilinx/Vivado/2014.2/settings64.sh
MIGEN_SRCS="virtmem movingaverage"

PROJ_DIR=/home/nengel/Documents/development/Riffa/riffa_2.1/source/fpga/kc705_clean
PROJ_NAME=kc705_pcie_x8_gen2_example
TOP_NAME=riffa_top_pcie_7x_v2_1

source $XIL_SETTINGS

set -e

cd $PROJ_DIR

for SRC in $MIGEN_SRCS
do
	rm -f $SRC.v
	echo "python3 $SRC.py > $SRC.v"
	python3 $SRC.py > $SRC.v
done

cd $PROJ_DIR/$PROJ_NAME

echo "vivado -mode batch -source ${TOP_NAME}_batch.tcl"
vivado -mode batch -source ${TOP_NAME}_batch.tcl

echo "scp -P 3389 $PROJ_DIR/$PROJ_NAME/$PROJ_NAME.runs/impl_1/${TOP_NAME}.bit nengel@hku-casr.no-ip.org:/home/nengel/kc705_program/"
scp -P 3389 $PROJ_DIR/$PROJ_NAME/$PROJ_NAME.runs/impl_1/${TOP_NAME}.bit nengel@hku-casr.no-ip.org:/home/nengel/kc705_program/
