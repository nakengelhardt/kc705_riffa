set_property IOSTANDARD LVCMOS25 [get_ports emcclk]
set_property PACKAGE_PIN R24 [get_ports emcclk]

set_property BITSTREAM.CONFIG.BPI_SYNC_MODE Type2 [current_design]
set_property BITSTREAM.CONFIG.EXTMASTERCCLK_EN div-2 [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
