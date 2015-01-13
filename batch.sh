#!/bin/bash

XIL_SETTINGS=/opt/Xilinx/Vivado/2014.2/settings64.sh
MIGEN_SRCS="count"

PROJ_DIR=/home/nengel/Documents/development/Riffa/riffa_2.1/source/fpga/kc705_clean
PROJ_NAME=kc705_pcie_x8_gen2_example
TOP_NAME=riffa_top_pcie_7x_v2_1
if [ -z "$IMPL_RUN" ]; then
	IMPL_RUN=1
fi

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

echo "open_project $PROJ_DIR/$PROJ_NAME/$PROJ_NAME.xpr
reset_run synth_1
launch_runs synth_1
wait_on_run synth_1
launch_runs impl_${IMPL_RUN}
wait_on_run impl_${IMPL_RUN}
launch_runs impl_${IMPL_RUN} -to_step write_bitstream
wait_on_run impl_${IMPL_RUN}
quit" > ${TOP_NAME}_batch.tcl

echo "vivado -mode batch -source ${TOP_NAME}_batch.tcl"
vivado -mode batch -source ${TOP_NAME}_batch.tcl

#echo "scp -P 3389 $PROJ_DIR/$PROJ_NAME/$PROJ_NAME.runs/impl_${IMPL_RUN}/${TOP_NAME}.bit nengel@hku-casr.no-ip.org:/home/nengel/kc705_program/"
#scp -P 3389 $PROJ_DIR/$PROJ_NAME/$PROJ_NAME.runs/impl_${IMPL_RUN}/${TOP_NAME}.bit nengel@hku-casr.no-ip.org:/home/nengel/kc705_program/
echo "scp -P 3389 nengel@nak.duckdns.org:$PROJ_DIR/$PROJ_NAME/$PROJ_NAME.runs/impl_${IMPL_RUN}/${TOP_NAME}.bit ."
