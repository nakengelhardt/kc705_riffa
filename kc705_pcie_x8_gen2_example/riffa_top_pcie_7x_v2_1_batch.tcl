open_project /home/nengel/Documents/development/Riffa/riffa_2.1/source/fpga/kc705_clean/kc705_pcie_x8_gen2_example/kc705_pcie_x8_gen2_example.xpr
reset_run synth_1
launch_runs synth_1
wait_on_run synth_1
launch_runs impl_1
wait_on_run impl_1
launch_runs impl_1 -to_step write_bitstream
wait_on_run impl_1
quit