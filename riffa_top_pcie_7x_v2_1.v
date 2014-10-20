//-----------------------------------------------------------------------------
// Project    : Series-7 Integrated Block for PCI Express
// File       : xilinx_pcie_2_1_ep_7x.v
// Version    : 3.0
//--
//-- Description:  PCI Express Endpoint example FPGA design
//--
//------------------------------------------------------------------------------

`timescale 1ns / 1ps
(* DowngradeIPIdentifiedWarnings = "yes" *)
//module xilinx_pcie_2_1_ep_7x # (
module riffa_top_pcie_7x_v2_1 # (
  parameter PL_FAST_TRAIN       = "FALSE", // Simulation Speedup
  parameter PCIE_EXT_CLK        = "TRUE",    // Use External Clocking Module
  parameter PCIE_EXT_GT_COMMON  = "FALSE",
  parameter REF_CLK_FREQ        = 0,     // 0 - 100 MHz, 1 - 125 MHz, 2 - 250 MHz
  parameter C_DATA_WIDTH        = 128, // RX/TX interface data width
  parameter KEEP_WIDTH          = C_DATA_WIDTH / 8 // TSTRB width
) (
  output  [7:0]    pci_exp_txp,
  output  [7:0]    pci_exp_txn,
  input   [7:0]    pci_exp_rxp,
  input   [7:0]    pci_exp_rxn,


  output                                      led_0,
  output                                      led_1,
  output                                      led_2,
  output                                      led_3,

  (* DONT_TOUCH = "TRUE" *) input             emcclk, // added as per AR#44635, XTP197

  input                                       sys_clk_p,
  input                                       sys_clk_n,
  input                                       sys_rst_n
);

// Wire Declarations
  wire                                        pipe_mmcm_rst_n;

  wire                                        user_clk;
  wire                                        user_reset;
  wire                                        user_lnk_up;

  // Tx
  wire [5:0]                                  tx_buf_av; //copied from vc707
  wire                                        tx_cfg_req; //copied from vc707
  wire                                        tx_err_drop; //copied from vc707
  wire                                        tx_cfg_gnt;
  wire                                        s_axis_tx_tready;
  wire [3:0]                                  s_axis_tx_tuser;
  wire [C_DATA_WIDTH-1:0]                     s_axis_tx_tdata;
  wire [KEEP_WIDTH-1:0]                       s_axis_tx_tkeep;
  wire                                        s_axis_tx_tlast;
  wire                                        s_axis_tx_tvalid;

  // Rx
  wire [C_DATA_WIDTH-1:0]                     m_axis_rx_tdata;
  wire [KEEP_WIDTH-1:0]                       m_axis_rx_tkeep;
  wire                                        m_axis_rx_tlast;
  wire                                        m_axis_rx_tvalid;
  wire                                        m_axis_rx_tready;
  wire  [21:0]                                m_axis_rx_tuser;
  wire                                        rx_np_ok;
  wire                                        rx_np_req;

  // Flow Control
  wire [11:0]                                 fc_cpld; //copied from vc707
  wire [7:0]                                  fc_cplh; //copied from vc707
  wire [11:0]                                 fc_npd; //copied from vc707
  wire [7:0]                                  fc_nph; //copied from vc707
  wire [11:0]                                 fc_pd; //copied from vc707
  wire [7:0]                                  fc_ph; //copied from vc707
  wire [2:0]                                  fc_sel;

  //-------------------------------------------------------
  // Configuration (CFG) Interface
  //-------------------------------------------------------
  wire                                        cfg_err_cor;
  wire                                        cfg_err_ur;
  wire                                        cfg_err_ecrc;
  wire                                        cfg_err_cpl_timeout;
  wire                                        cfg_err_cpl_abort;
  wire                                        cfg_err_cpl_unexpect;
  wire                                        cfg_err_posted;
  wire                                        cfg_err_locked;
  wire  [47:0]                                cfg_err_tlp_cpl_header;
  wire                                        cfg_err_cpl_rdy; //copied from vc707
  wire                                        cfg_interrupt;
  wire                                        cfg_interrupt_rdy; //copied from vc707
  wire                                        cfg_interrupt_assert;
  wire   [7:0]                                cfg_interrupt_di;
  wire   [7:0]                                cfg_interrupt_do; //copied from vc707
  wire   [2:0]                                cfg_interrupt_mmenable; //copied from vc707
  wire                                        cfg_interrupt_msienable; //copied from vc707
  wire                                        cfg_interrupt_msixenable; //copied from vc707
  wire                                        cfg_interrupt_msixfm; //copied from vc707
  wire                                        cfg_interrupt_stat;
  wire   [4:0]                                cfg_pciecap_interrupt_msgnum;
  wire                                        cfg_turnoff_ok;
  wire                                        cfg_to_turnoff;
  wire                                        cfg_trn_pending;
  wire                                        cfg_pm_halt_aspm_l0s;
  wire                                        cfg_pm_halt_aspm_l1;
  wire                                        cfg_pm_force_state_en;
  wire   [1:0]                                cfg_pm_force_state;
  wire                                        cfg_pm_wake;
  wire   [7:0]                                cfg_bus_number;
  wire   [4:0]                                cfg_device_number;
  wire   [2:0]                                cfg_function_number;
  wire  [15:0]                                cfg_status; //copied from vc707
  wire  [15:0]                                cfg_command; //copied from vc707
  wire  [15:0]                                cfg_dstatus; //copied from vc707
  wire  [15:0]                                cfg_dcommand; //copied from vc707
  wire  [15:0]                                cfg_lstatus; //copied from vc707
  wire  [15:0]                                cfg_lcommand; //copied from vc707
  wire  [15:0]                                cfg_dcommand2; //copied from vc707
  wire   [2:0]                                cfg_pcie_link_state; //copied from vc707
  wire  [63:0]                                cfg_dsn;
  wire [127:0]                                cfg_err_aer_headerlog;
  wire   [4:0]                                cfg_aer_interrupt_msgnum;
  wire                                        cfg_err_aer_headerlog_set; //copied from vc707
  wire                                        cfg_aer_ecrc_check_en; //copied from vc707
  wire                                        cfg_aer_ecrc_gen_en; //copied from vc707

  wire  [31:0]                                cfg_mgmt_di;
  wire   [3:0]                                cfg_mgmt_byte_en;
  wire   [9:0]                                cfg_mgmt_dwaddr;
  wire                                        cfg_mgmt_wr_en;
  wire                                        cfg_mgmt_rd_en;
  wire                                        cfg_mgmt_wr_readonly;

  //-------------------------------------------------------
  // Physical Layer Control and Status (PL) Interface
  //-------------------------------------------------------
  wire [2:0]                                  pl_initial_link_width; //copied from vc707
  wire [1:0]                                  pl_lane_reversal_mode; //copied from vc707
  wire                                        pl_link_gen2_cap; //copied from vc707
  wire                                        pl_link_partner_gen2_supported; //copied from vc707
  wire                                        pl_link_upcfg_cap; //copied from vc707
  wire [5:0]                                  pl_ltssm_state; //copied from vc707
  wire                                        pl_received_hot_rst; //copied from vc707
  wire                                        pl_sel_lnk_rate; //copied from vc707
  wire [1:0]                                  pl_sel_lnk_width; //copied from vc707
  wire                                        pl_directed_link_auton;
  wire [1:0]                                  pl_directed_link_change;
  wire                                        pl_directed_link_speed;
  wire [1:0]                                  pl_directed_link_width;
  wire                                        pl_upstream_prefer_deemph;

  wire                                        sys_rst_n_c;
  wire                                        sys_clk;


// Register Declaration

  reg                                         user_reset_q;
  reg                                         user_lnk_up_q;
  reg    [25:0]                               user_clk_heartbeat = 'h0;

// Local Parameters
  localparam TCQ               = 1;
  localparam USER_CLK_FREQ     = 4;
  localparam USER_CLK2_DIV2    = "TRUE";
  localparam USERCLK2_FREQ     = (USER_CLK2_DIV2 == "TRUE") ? (USER_CLK_FREQ == 4) ? 3 : (USER_CLK_FREQ == 3) ? 2 : USER_CLK_FREQ: USER_CLK_FREQ;

 //-----------------------------I/O BUFFERS------------------------//

  IBUF   sys_reset_n_ibuf (.O(sys_rst_n_c), .I(sys_rst_n));

  IBUFDS_GTE2 refclk_ibuf (.O(sys_clk), .ODIV2(), .I(sys_clk_p), .CEB(1'b0), .IB(sys_clk_n));

  OBUF   led_0_obuf (.O(led_0), .I(sys_rst_n_c));
  OBUF   led_1_obuf (.O(led_1), .I(!user_reset));
  OBUF   led_2_obuf (.O(led_2), .I(user_lnk_up));
  OBUF   led_3_obuf (.O(led_3), .I(user_clk_heartbeat[25]));

  always @(posedge user_clk) begin
    user_reset_q  <= user_reset;
    user_lnk_up_q <= user_lnk_up;
  end

  // Create a Clock Heartbeat on LED #3
  always @(posedge user_clk) begin
      user_clk_heartbeat <= #TCQ user_clk_heartbeat + 1'b1;
  end


      assign pipe_mmcm_rst_n                        = 1'b1;



kc705_pcie_x8_gen2_support #
   (	 
    .LINK_CAP_MAX_LINK_WIDTH        ( 8 ),  // PCIe Lane Width
    .C_DATA_WIDTH                   ( C_DATA_WIDTH ),                       // RX/TX interface data width
    .KEEP_WIDTH                     ( KEEP_WIDTH ),                         // TSTRB width
    .PCIE_REFCLK_FREQ               ( REF_CLK_FREQ ),                       // PCIe reference clock frequency
    .PCIE_USERCLK1_FREQ             ( USER_CLK_FREQ +1 ),                   // PCIe user clock 1 frequency
    .PCIE_USERCLK2_FREQ             ( USERCLK2_FREQ +1 ),                   // PCIe user clock 2 frequency             
    .PCIE_USE_MODE                  ("3.0"),           // PCIe use mode
    .PCIE_GT_DEVICE                 ("GTX")              // PCIe GT device
   ) 
kc705_pcie_x8_gen2_support_i
  (

  //----------------------------------------------------------------------------------------------------------------//
  // PCI Express (pci_exp) Interface                                                                                //
  //----------------------------------------------------------------------------------------------------------------//
  // Tx
  .pci_exp_txn                               ( pci_exp_txn ),
  .pci_exp_txp                               ( pci_exp_txp ),

  // Rx
  .pci_exp_rxn                               ( pci_exp_rxn ),
  .pci_exp_rxp                               ( pci_exp_rxp ),

  //----------------------------------------------------------------------------------------------------------------//
  // Clocking Sharing Interface                                                                                     //
  //----------------------------------------------------------------------------------------------------------------//
  .pipe_pclk_out_slave                        ( ),
  .pipe_rxusrclk_out                          ( ),
  .pipe_rxoutclk_out                          ( ),
  .pipe_dclk_out                              ( ),
  .pipe_userclk1_out                          ( ),
  .pipe_oobclk_out                            ( ),
  .pipe_userclk2_out                          ( ),
  .pipe_mmcm_lock_out                         ( ),
  .pipe_pclk_sel_slave                        ( 8'b0),
  .pipe_mmcm_rst_n                            ( pipe_mmcm_rst_n ),        // Async      | Async


  //----------------------------------------------------------------------------------------------------------------//
  // AXI-S Interface                                                                                                //
  //----------------------------------------------------------------------------------------------------------------//

  // Common
  .user_clk_out                              ( user_clk ),
  .user_reset_out                            ( user_reset ),
  .user_lnk_up                               ( user_lnk_up ),
  .user_app_rdy                              ( ),

  // TX
  .s_axis_tx_tready                          ( s_axis_tx_tready ),
  .s_axis_tx_tdata                           ( s_axis_tx_tdata ),
  .s_axis_tx_tkeep                           ( s_axis_tx_tkeep ),
  .s_axis_tx_tuser                           ( s_axis_tx_tuser ),
  .s_axis_tx_tlast                           ( s_axis_tx_tlast ),
  .s_axis_tx_tvalid                          ( s_axis_tx_tvalid ),

  // Rx
  .m_axis_rx_tdata                           ( m_axis_rx_tdata ),
  .m_axis_rx_tkeep                           ( m_axis_rx_tkeep ),
  .m_axis_rx_tlast                           ( m_axis_rx_tlast ),
  .m_axis_rx_tvalid                          ( m_axis_rx_tvalid ),
  .m_axis_rx_tready                          ( m_axis_rx_tready ),
  .m_axis_rx_tuser                           ( m_axis_rx_tuser ),

  // Flow Control
  .fc_cpld                                   ( fc_cpld ), //filled in manually
  .fc_cplh                                   ( fc_cplh ), //filled in manually
  .fc_npd                                    ( fc_npd ), //filled in manually
  .fc_nph                                    ( fc_nph ), //filled in manually
  .fc_pd                                     ( fc_pd ), //filled in manually
  .fc_ph                                     ( fc_ph ), //filled in manually
  .fc_sel                                    ( fc_sel ),

  // Management Interface
  .cfg_mgmt_di                               ( cfg_mgmt_di ),
  .cfg_mgmt_byte_en                          ( cfg_mgmt_byte_en ),
  .cfg_mgmt_dwaddr                           ( cfg_mgmt_dwaddr ),
  .cfg_mgmt_wr_en                            ( cfg_mgmt_wr_en ),
  .cfg_mgmt_rd_en                            ( cfg_mgmt_rd_en ),
  .cfg_mgmt_wr_readonly                      ( cfg_mgmt_wr_readonly ),

  //------------------------------------------------//
  // EP and RP                                      //
  //------------------------------------------------//
  .cfg_mgmt_do                               ( ),
  .cfg_mgmt_rd_wr_done                       ( ),
  .cfg_mgmt_wr_rw1c_as_rw                    ( 1'b0 ),

  // Error Reporting Interface
  .cfg_err_ecrc                              ( cfg_err_ecrc ),
  .cfg_err_ur                                ( cfg_err_ur ),
  .cfg_err_cpl_timeout                       ( cfg_err_cpl_timeout ),
  .cfg_err_cpl_unexpect                      ( cfg_err_cpl_unexpect ),
  .cfg_err_cpl_abort                         ( cfg_err_cpl_abort ),
  .cfg_err_posted                            ( cfg_err_posted ),
  .cfg_err_cor                               ( cfg_err_cor ),
  .cfg_err_atomic_egress_blocked             ( cfg_err_atomic_egress_blocked ),
  .cfg_err_internal_cor                      ( cfg_err_internal_cor ),
  .cfg_err_malformed                         ( cfg_err_malformed ),
  .cfg_err_mc_blocked                        ( cfg_err_mc_blocked ),
  .cfg_err_poisoned                          ( cfg_err_poisoned ),
  .cfg_err_norecovery                        ( cfg_err_norecovery ),
  .cfg_err_tlp_cpl_header                    ( cfg_err_tlp_cpl_header ),
  .cfg_err_cpl_rdy                           ( cfg_err_cpl_rdy ), //filled in manually
  .cfg_err_locked                            ( cfg_err_locked ),
  .cfg_err_acs                               ( cfg_err_acs ),
  .cfg_err_internal_uncor                    ( cfg_err_internal_uncor ),

  //----------------------------------------------------------------------------------------------------------------//
  // AER Interface                                                                                                  //
  //----------------------------------------------------------------------------------------------------------------//
  .cfg_err_aer_headerlog                     ( cfg_err_aer_headerlog ),
  .cfg_err_aer_headerlog_set                 ( cfg_err_aer_headerlog_set ), //filled in manually
  .cfg_aer_ecrc_check_en                     ( cfg_aer_ecrc_check_en ), //filled in manually
  .cfg_aer_ecrc_gen_en                       ( cfg_aer_ecrc_gen_en ), //filled in manually
  .cfg_aer_interrupt_msgnum                  ( cfg_aer_interrupt_msgnum ),

  .tx_cfg_gnt                                ( tx_cfg_gnt ),
  .rx_np_ok                                  ( rx_np_ok ),
  .rx_np_req                                 ( rx_np_req ),
  .cfg_trn_pending                           ( cfg_trn_pending ),
  .cfg_pm_halt_aspm_l0s                      ( cfg_pm_halt_aspm_l0s ),
  .cfg_pm_halt_aspm_l1                       ( cfg_pm_halt_aspm_l1 ),
  .cfg_pm_force_state_en                     ( cfg_pm_force_state_en ),
  .cfg_pm_force_state                        ( cfg_pm_force_state ),
  .cfg_dsn                                   ( cfg_dsn ),
  .cfg_turnoff_ok                            ( cfg_turnoff_ok ),
  .cfg_pm_wake                               ( cfg_pm_wake ),
  //------------------------------------------------//
  // RP Only                                        //
  //------------------------------------------------//
  .cfg_pm_send_pme_to                        ( 1'b0 ),
  .cfg_ds_bus_number                         ( 8'b0 ),
  .cfg_ds_device_number                      ( 5'b0 ),
  .cfg_ds_function_number                    ( 3'b0 ),

  //------------------------------------------------//
  // EP Only                                        //
  //------------------------------------------------//
  .cfg_interrupt                             ( cfg_interrupt ),
  .cfg_interrupt_rdy                         ( cfg_interrupt_rdy ), //filled in manually
  .cfg_interrupt_assert                      ( cfg_interrupt_assert ),
  .cfg_interrupt_di                          ( cfg_interrupt_di ),
  .cfg_interrupt_do                          ( cfg_interrupt_do ), //filled in manually
  .cfg_interrupt_mmenable                    ( cfg_interrupt_mmenable ), //filled in manually
  .cfg_interrupt_msienable                   ( cfg_interrupt_msienable ), //filled in manually
  .cfg_interrupt_msixenable                  ( cfg_interrupt_msixenable ), //filled in manually
  .cfg_interrupt_msixfm                      ( cfg_interrupt_msixfm ), //filled in manually
  .cfg_interrupt_stat                        ( cfg_interrupt_stat ),
  .cfg_pciecap_interrupt_msgnum              ( cfg_pciecap_interrupt_msgnum ),

  //----------------------------------------------------------------------------------------------------------------//
  // Configuration (CFG) Interface                                                                                  //
  //----------------------------------------------------------------------------------------------------------------//
  .cfg_status                                ( cfg_status ), //filled in manually
  .cfg_command                               ( cfg_command ), //filled in manually
  .cfg_dstatus                               ( cfg_dstatus ), //filled in manually
  .cfg_lstatus                               ( cfg_lstatus ), //filled in manually
  .cfg_pcie_link_state                       ( cfg_pcie_link_state ), //filled in manually
  .cfg_dcommand                              ( cfg_dcommand ), //filled in manually
  .cfg_lcommand                              ( cfg_lcommand ), //filled in manually
  .cfg_dcommand2                             ( cfg_dcommand2 ), //filled in manually

  .cfg_pmcsr_pme_en                          ( ),
  .cfg_pmcsr_powerstate                      ( ),
  .cfg_pmcsr_pme_status                      ( ),
  .cfg_received_func_lvl_rst                 ( ),
  .tx_buf_av                                 ( tx_buf_av ), //filled in manually
  .tx_err_drop                               ( tx_err_drop ), //filled in manually
  .tx_cfg_req                                ( tx_cfg_req ), //filled in manually
  .cfg_to_turnoff                            ( cfg_to_turnoff ),
  .cfg_bus_number                            ( cfg_bus_number ),
  .cfg_device_number                         ( cfg_device_number ),
  .cfg_function_number                       ( cfg_function_number ),
  .cfg_bridge_serr_en                        ( ),
  .cfg_slot_control_electromech_il_ctl_pulse ( ),
  .cfg_root_control_syserr_corr_err_en       ( ),
  .cfg_root_control_syserr_non_fatal_err_en  ( ),
  .cfg_root_control_syserr_fatal_err_en      ( ),
  .cfg_root_control_pme_int_en               ( ),
  .cfg_aer_rooterr_corr_err_reporting_en     ( ),
  .cfg_aer_rooterr_non_fatal_err_reporting_en( ),
  .cfg_aer_rooterr_fatal_err_reporting_en    ( ),
  .cfg_aer_rooterr_corr_err_received         ( ),
  .cfg_aer_rooterr_non_fatal_err_received    ( ),
  .cfg_aer_rooterr_fatal_err_received        ( ),
  //----------------------------------------------------------------------------------------------------------------//
  // VC interface                                                                                                  //
  //---------------------------------------------------------------------------------------------------------------//
  .cfg_vc_tcvc_map                           ( ),

  .cfg_msg_received                          ( ),
  .cfg_msg_data                              ( ),
  .cfg_msg_received_err_cor                  ( ),
  .cfg_msg_received_err_non_fatal            ( ),
  .cfg_msg_received_err_fatal                ( ),
  .cfg_msg_received_pm_as_nak                ( ),
  .cfg_msg_received_pme_to_ack               ( ),
  .cfg_msg_received_assert_int_a             ( ),
  .cfg_msg_received_assert_int_b             ( ),
  .cfg_msg_received_assert_int_c             ( ),
  .cfg_msg_received_assert_int_d             ( ),
  .cfg_msg_received_deassert_int_a           ( ),
  .cfg_msg_received_deassert_int_b           ( ),
  .cfg_msg_received_deassert_int_c           ( ),
  .cfg_msg_received_deassert_int_d           ( ),
  .cfg_msg_received_pm_pme                  ( ),
  .cfg_msg_received_setslotpowerlimit       ( ),

  //----------------------------------------------------------------------------------------------------------------//
  // Physical Layer Control and Status (PL) Interface                                                               //
  //----------------------------------------------------------------------------------------------------------------//
  .pl_directed_link_change                   ( pl_directed_link_change ),
  .pl_directed_link_width                    ( pl_directed_link_width ),
  .pl_directed_link_speed                    ( pl_directed_link_speed ),
  .pl_directed_link_auton                    ( pl_directed_link_auton ),
  .pl_upstream_prefer_deemph                 ( pl_upstream_prefer_deemph ),

  .pl_sel_lnk_rate                           ( pl_sel_lnk_rate ), //filled in manually
  .pl_sel_lnk_width                          ( pl_sel_lnk_width ), //filled in manually
  .pl_ltssm_state                            ( pl_ltssm_state ), //filled in manually
  .pl_lane_reversal_mode                     ( pl_lane_reversal_mode ), //filled in manually

  .pl_phy_lnk_up                             ( ),
  .pl_tx_pm_state                            ( ),
  .pl_rx_pm_state                            ( ),

  .pl_link_upcfg_cap                         ( pl_link_upcfg_cap ), //filled in manually
  .pl_link_gen2_cap                          ( pl_link_gen2_cap ), //filled in manually
  .pl_link_partner_gen2_supported            ( pl_link_partner_gen2_supported ), //filled in manually
  .pl_initial_link_width                     ( pl_initial_link_width ), //filled in manually

  .pl_directed_change_done                   ( ),

  //------------------------------------------------//
  // EP Only                                        //
  //------------------------------------------------//
  .pl_received_hot_rst                       ( pl_received_hot_rst ), //filled in manually

  //------------------------------------------------//
  // RP Only                                        //
  //------------------------------------------------//
  .pl_transmit_hot_rst                       ( 1'b0 ),
  .pl_downstream_deemph_source               ( 1'b0 ),




  //----------------------------------------------------------------------------------------------------------------//
  // System  (SYS) Interface                                                                                        //
  //----------------------------------------------------------------------------------------------------------------//
  .sys_clk                                    ( sys_clk ),
  .sys_rst_n                                  ( sys_rst_n_c )

);


pcie_app_7x  #(
  .C_DATA_WIDTH( C_DATA_WIDTH ),
  .TCQ( TCQ )

) app (

  //----------------------------------------------------------------------------------------------------------------//
  // AXI-S Interface                                                                                                //
  //----------------------------------------------------------------------------------------------------------------//

  // Common
  .user_clk                       ( user_clk ),
  .user_reset                     ( user_reset_q ),
  .user_lnk_up                    ( user_lnk_up_q ),

  // Tx
  .tx_buf_av                      ( tx_buf_av ), //copied from vc707
  .tx_cfg_req                     ( tx_cfg_req ), //copied from vc707
  .tx_err_drop                    ( tx_err_drop ), //copied from vc707
  .s_axis_tx_tready               ( s_axis_tx_tready ),
  .s_axis_tx_tdata                ( s_axis_tx_tdata ),
  .s_axis_tx_tkeep                ( s_axis_tx_tkeep ),
  .s_axis_tx_tuser                ( s_axis_tx_tuser ),
  .s_axis_tx_tlast                ( s_axis_tx_tlast ),
  .s_axis_tx_tvalid               ( s_axis_tx_tvalid ),
  .tx_cfg_gnt                     ( tx_cfg_gnt ),

  // Rx
  .m_axis_rx_tdata                ( m_axis_rx_tdata ),
  .m_axis_rx_tkeep                ( m_axis_rx_tkeep ),
  .m_axis_rx_tlast                ( m_axis_rx_tlast ),
  .m_axis_rx_tvalid               ( m_axis_rx_tvalid ),
  .m_axis_rx_tready               ( m_axis_rx_tready ),
  .m_axis_rx_tuser                ( m_axis_rx_tuser ),

  .rx_np_ok                       ( rx_np_ok ),
  .rx_np_req                      ( rx_np_req ),

  // Flow Control
  .fc_cpld                        ( fc_cpld ), //copied from vc707
  .fc_cplh                        ( fc_cplh ), //copied from vc707
  .fc_npd                         ( fc_npd ), //copied from vc707
  .fc_nph                         ( fc_nph ), //copied from vc707
  .fc_pd                          ( fc_pd ), //copied from vc707
  .fc_ph                          ( fc_ph ), //copied from vc707
  .fc_sel                         ( fc_sel ),

  //----------------------------------------------------------------------------------------------------------------//
  // Configuration (CFG) Interface                                                                                  //
  //----------------------------------------------------------------------------------------------------------------//
  .cfg_err_cor                    ( cfg_err_cor ),
  .cfg_err_atomic_egress_blocked  ( cfg_err_atomic_egress_blocked ),
  .cfg_err_internal_cor           ( cfg_err_internal_cor ),
  .cfg_err_malformed              ( cfg_err_malformed ),
  .cfg_err_mc_blocked             ( cfg_err_mc_blocked ),
  .cfg_err_poisoned               ( cfg_err_poisoned ),
  .cfg_err_norecovery             ( cfg_err_norecovery ),
  .cfg_err_ur                     ( cfg_err_ur ),
  .cfg_err_ecrc                   ( cfg_err_ecrc ),
  .cfg_err_cpl_timeout            ( cfg_err_cpl_timeout ),
  .cfg_err_cpl_abort              ( cfg_err_cpl_abort ),
  .cfg_err_cpl_unexpect           ( cfg_err_cpl_unexpect ),
  .cfg_err_posted                 ( cfg_err_posted ),
  .cfg_err_locked                 ( cfg_err_locked ),
  .cfg_err_acs                    ( cfg_err_acs ), //1'b0 ),
  .cfg_err_internal_uncor         ( cfg_err_internal_uncor ), //1'b0 ),
  .cfg_err_tlp_cpl_header         ( cfg_err_tlp_cpl_header ),
  .cfg_err_cpl_rdy                ( cfg_err_cpl_rdy ), //copied from vc707
  .cfg_interrupt                  ( cfg_interrupt ),
  .cfg_interrupt_rdy              ( cfg_interrupt_rdy ), //copied from vc707
  .cfg_interrupt_assert           ( cfg_interrupt_assert ),
  .cfg_interrupt_di               ( cfg_interrupt_di ),
  .cfg_interrupt_do               ( cfg_interrupt_do ), //copied from vc707
  .cfg_interrupt_mmenable         ( cfg_interrupt_mmenable ), //copied from vc707
  .cfg_interrupt_msienable        ( cfg_interrupt_msienable ), //copied from vc707
  .cfg_interrupt_msixenable       ( cfg_interrupt_msixenable ), //copied from vc707
  .cfg_interrupt_msixfm           ( cfg_interrupt_msixfm ), //copied from vc707
  .cfg_interrupt_stat             ( cfg_interrupt_stat ),
  .cfg_pciecap_interrupt_msgnum   ( cfg_pciecap_interrupt_msgnum ),
  .cfg_turnoff_ok                 ( cfg_turnoff_ok ),
  .cfg_to_turnoff                 ( cfg_to_turnoff ),

  .cfg_trn_pending                ( cfg_trn_pending ),
  .cfg_pm_halt_aspm_l0s           ( cfg_pm_halt_aspm_l0s ),
  .cfg_pm_halt_aspm_l1            ( cfg_pm_halt_aspm_l1 ),
  .cfg_pm_force_state_en          ( cfg_pm_force_state_en ),
  .cfg_pm_force_state             ( cfg_pm_force_state ),

  .cfg_pm_wake                    ( cfg_pm_wake ),
  .cfg_bus_number                 ( cfg_bus_number ),
  .cfg_device_number              ( cfg_device_number ),
  .cfg_function_number            ( cfg_function_number ),
  .cfg_status                     ( cfg_status ), //copied from vc707
  .cfg_command                    ( cfg_command ), //copied from vc707
  .cfg_dstatus                    ( cfg_dstatus ), //copied from vc707
  .cfg_dcommand                   ( cfg_dcommand ), //copied from vc707
  .cfg_lstatus                    ( cfg_lstatus ), //copied from vc707
  .cfg_lcommand                   ( cfg_lcommand ), //copied from vc707
  .cfg_dcommand2                  ( cfg_dcommand2 ), //copied from vc707
  .cfg_pcie_link_state            ( cfg_pcie_link_state ), //copied from vc707
  .cfg_dsn                        ( cfg_dsn ),

  //----------------------------------------------------------------------------------------------------------------//
  // Management (MGMT) Interface                                                                                    //
  //----------------------------------------------------------------------------------------------------------------//
  .cfg_mgmt_di                    ( cfg_mgmt_di ),
  .cfg_mgmt_byte_en               ( cfg_mgmt_byte_en ),
  .cfg_mgmt_dwaddr                ( cfg_mgmt_dwaddr ),
  .cfg_mgmt_wr_en                 ( cfg_mgmt_wr_en ),
  .cfg_mgmt_rd_en                 ( cfg_mgmt_rd_en ),
  .cfg_mgmt_wr_readonly           ( cfg_mgmt_wr_readonly ),

  //----------------------------------------------------------------------------------------------------------------//
  // Advanced Error Reporting (AER) Interface                                                                       //
  //----------------------------------------------------------------------------------------------------------------//
  .cfg_err_aer_headerlog          ( cfg_err_aer_headerlog ),
  .cfg_aer_interrupt_msgnum       ( cfg_aer_interrupt_msgnum ),
  .cfg_err_aer_headerlog_set      ( cfg_err_aer_headerlog_set ), //copied from vc707
  .cfg_aer_ecrc_check_en          ( cfg_aer_ecrc_check_en ), //copied from vc707
  .cfg_aer_ecrc_gen_en            ( cfg_aer_ecrc_gen_en ), //copied from vc707

  //----------------------------------------------------------------------------------------------------------------//
  // Physical Layer Control and Status (PL) Interface                                                               //
  //----------------------------------------------------------------------------------------------------------------//
  .pl_initial_link_width          ( pl_initial_link_width ), //copied from vc707
  .pl_lane_reversal_mode          ( pl_lane_reversal_mode ), //copied from vc707
  .pl_link_gen2_cap               ( pl_link_gen2_cap ), //copied from vc707
  .pl_link_partner_gen2_supported ( pl_link_partner_gen2_supported ), //copied from vc707
  .pl_link_upcfg_cap              ( pl_link_upcfg_cap ), //copied from vc707
  .pl_ltssm_state                 ( pl_ltssm_state ), //copied from vc707
  .pl_received_hot_rst            ( pl_received_hot_rst ), //copied from vc707
  .pl_sel_lnk_rate                ( pl_sel_lnk_rate ), //copied from vc707
  .pl_sel_lnk_width               ( pl_sel_lnk_width ), //copied from vc707
  .pl_directed_link_auton         ( pl_directed_link_auton ),
  .pl_directed_link_change        ( pl_directed_link_change ),
  .pl_directed_link_speed         ( pl_directed_link_speed ),
  .pl_directed_link_width         ( pl_directed_link_width ),
  .pl_upstream_prefer_deemph      ( pl_upstream_prefer_deemph )

);

endmodule
